from __future__ import annotations

import os
import sys
import inspect
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-for-coach-context-v2!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")

import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from training_v2.plan_goal import GoalType  # noqa: E402


_USER_ID = "coach-user"
_USER_EMAIL = "coach@example.com"
_REFERENCE_DATE = date(2026, 9, 17)


def _bearer(user_id: str = _USER_ID, email: str = _USER_EMAIL) -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _user_doc(user_id: str = _USER_ID, email: str = _USER_EMAIL) -> dict:
    return {
        "id": user_id,
        "email": email,
        "is_active": True,
        "is_email_verified": True,
    }


def _matches(document: dict, query: dict) -> bool:
    for key, expected in (query or {}).items():
        actual = document.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
            if "$lte" in expected and (actual is None or actual > expected["$lte"]):
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
        elif actual != expected:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        reverse = direction == -1
        self._docs = sorted(self._docs, key=lambda doc: doc.get(key), reverse=reverse)
        return self

    def limit(self, count):
        self._docs = self._docs[:count]
        return self

    async def to_list(self, length=None):
        return list(self._docs if length is None else self._docs[:length])


class _Collection:
    def __init__(self, docs=None):
        self._docs = [dict(doc) for doc in (docs or [])]
        self.find_one_calls: list[dict] = []

    async def find_one(self, query, projection=None, sort=None):
        self.find_one_calls.append(dict(query))
        docs = [dict(doc) for doc in self._docs if _matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: doc.get(key), reverse=direction == -1)
        return docs[0] if docs else None

    def find(self, query=None, projection=None):
        return _Cursor(dict(doc) for doc in self._docs if _matches(doc, query or {}))

    async def insert_one(self, doc):
        self._docs.append(dict(doc))


class _ExplodingTrainingPlansCollection:
    def __init__(self):
        self.find_one_called = False
        self.find_called = False

    async def find_one(self, *args, **kwargs):
        self.find_one_called = True
        raise AssertionError("db.training_plans must not be accessed by /coach/analyze")

    def find(self, *args, **kwargs):
        self.find_called = True
        raise AssertionError("db.training_plans must not be accessed by /coach/analyze")


class _FakeDB:
    def __init__(self):
        self.users = _Collection([_user_doc(), _user_doc("other-user", "other@example.com")])
        self.conversations = _Collection([])
        self.garmin_activities = _Collection([
            {
                "user_id": _USER_ID,
                "start_time": "2026-09-16T06:00:00+00:00",
                "activity_type": "running",
            }
        ])
        self.garmin_connections = _Collection([{"user_id": _USER_ID, "connected": True}])
        self.garmin_daily_metrics = _Collection([{"user_id": _USER_ID, "date": "2026-09-17"}])
        self.training_prescription_snapshots = _Collection([
            {
                "user_id": _USER_ID,
                "prescription_id": "mon-id",
                "planned_date": "2026-09-14",
                "day": "monday",
                "workout_type": "easy_run",
                "intensity_class": "easy",
                "distance_km": 10.5,
                "duration_minutes": 60,
                "reason_codes": ["SNAPSHOT_MON"],
                "structured": {"kind": "structured-mon"},
                "modified_from_planned": False,
                "adaptation_action": "KEEP",
                "adaptation_reason_codes": [],
            },
            {
                "user_id": _USER_ID,
                "prescription_id": "thu-id",
                "planned_date": "2026-09-17",
                "day": "thursday",
                "workout_type": "tempo",
                "intensity_class": "quality",
                "distance_km": 6.4,
                "duration_minutes": 35,
                "reason_codes": ["SNAPSHOT_TODAY"],
                "structured": {"kind": "structured-today"},
                "modified_from_planned": True,
                "adaptation_action": "SHORTEN",
                "adaptation_reason_codes": ["READINESS_CAUTION"],
            },
        ])
        self.training_planned_prescription_memory = _Collection([
            {
                "user_id": _USER_ID,
                "prescription_id": "tue-id",
                "planned_date": "2026-09-15",
                "day": "tuesday",
                "workout_type": "steady",
                "intensity_class": "aerobic",
                "distance_km": 7.5,
                "duration_minutes": 42,
                "reason_codes": ["MEMORY_TUE"],
                "structured": {"kind": "memory-structured"},
            }
        ])
        self.workouts = _Collection([
            {
                "id": "foreign-workout",
                "user_id": "other-user",
                "name": "Someone else's run",
                "distance_km": 99.0,
                "duration_minutes": 999,
            }
        ])
        self.training_plans = _ExplodingTrainingPlansCollection()


def _week_payload() -> dict:
    return {
        "goal": {
            "goal_type": "marathon",
            "race_date": "2026-11-01",
            "target_time_seconds": 12600,
        },
        "state": {
            "continuity_state": "consistent",
            "allow_intensity": True,
        },
        "weekly_target": {
            "target_basis": "distance",
            "target_km": 58.0,
            "target_duration_minutes": None,
            "session_count": 5,
            "confidence": "high",
        },
        "reconciliation_action": "preserve",
        "reconciliation_reason_codes": ["ON_TRACK"],
        "week": {
            "sessions": [
                {
                    "day": "Monday",
                    "planned_date": "2026-09-14",
                    "prescription_id": "mon-id",
                    "workout_type": "easy_run",
                    "intensity_class": "easy",
                    "distance_km": 10.5,
                    "duration_minutes": 60,
                    "reason_codes": ["PLAN_MON"],
                    "matching_status": "matched",
                    "adherence_status": "completed_as_planned",
                    "execution_status": "executed",
                    "structured_status": "served_snapshot",
                    "session_modified_from_planned": False,
                    "structured": {"kind": "week-mon"},
                },
                {
                    "day": "Tuesday",
                    "planned_date": "2026-09-15",
                    "prescription_id": "tue-id",
                    "workout_type": "steady",
                    "intensity_class": "aerobic",
                    "distance_km": 9.0,
                    "duration_minutes": 50,
                    "reason_codes": ["PLAN_TUE_NEW_GOAL"],
                    "matching_status": None,
                    "adherence_status": None,
                    "execution_status": "executed",
                    "structured_status": "planned_memory",
                    "session_modified_from_planned": None,
                    "structured": {"kind": "week-tue"},
                },
                {
                    "day": "Wednesday",
                    "planned_date": "2026-09-16",
                    "prescription_id": "wed-id",
                    "workout_type": None,
                    "intensity_class": None,
                    "distance_km": None,
                    "duration_minutes": None,
                    "reason_codes": [],
                    "matching_status": None,
                    "adherence_status": None,
                    "execution_status": "prescription_unavailable",
                    "structured_status": "unavailable",
                    "session_modified_from_planned": None,
                    "structured": None,
                },
                {
                    "day": "Thursday",
                    "planned_date": "2026-09-17",
                    "prescription_id": "thu-id",
                    "workout_type": "tempo",
                    "intensity_class": "quality",
                    "distance_km": 8.0,
                    "duration_minutes": 42,
                    "reason_codes": ["PLAN_THU"],
                    "matching_status": None,
                    "adherence_status": None,
                    "execution_status": "executed",
                    "structured_status": "today_served",
                    "session_modified_from_planned": True,
                    "structured": {"kind": "week-thu"},
                },
                {
                    "day": "Friday",
                    "planned_date": "2026-09-18",
                    "prescription_id": "fri-id",
                    "workout_type": "long_run",
                    "intensity_class": "endurance",
                    "distance_km": 18.0,
                    "duration_minutes": 100,
                    "reason_codes": ["PLAN_FRI"],
                    "matching_status": None,
                    "adherence_status": None,
                    "execution_status": "planned",
                    "structured_status": "planned",
                    "session_modified_from_planned": None,
                    "structured": {"kind": "week-fri"},
                },
            ]
        },
    }


def _today_payload() -> dict:
    return {
        "status": "success",
        "date": "2026-09-17",
        "day": "Thursday",
        "prescription_id": "thu-id",
        "planned_session": {
            "workout_type": "tempo",
            "intensity_class": "quality",
            "distance_km": 8.0,
            "duration_minutes": 42,
        },
        "served_prescription": {
            "workout_type": "tempo",
            "intensity_class": "quality",
            "distance_km": 6.4,
            "duration_minutes": 35,
        },
        "session_modified_from_planned": True,
        "adaptation_applied": True,
        "adaptation_action": "SHORTEN",
        "adaptation_reason": "READINESS_CAUTION",
        "reason_codes": ["TODAY_PAYLOAD"],
        "structured_workout": {"kind": "today-payload"},
        "structured_status": "today_served",
    }


def _training_load(**overrides):
    values = {
        "acute_load_7d": 210.0,
        "load_28d": 780.0,
        "chronic_weekly_load": 195.0,
        "acwr": 1.08,
        "status": "balanced",
        "confidence": "high",
        "is_available": True,
        "has_sufficient_history": True,
        "load_change_percent": 7.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _readiness_decision(*, band="CAUTION", score=62.0, confidence="NORMAL", sufficiency="SUFFICIENT", reason_codes=("READINESS_CAUTION",)):
    return SimpleNamespace(
        band=SimpleNamespace(value=band),
        score=score,
        confidence=SimpleNamespace(value=confidence),
        sufficiency_level=SimpleNamespace(value=sufficiency),
        reason_codes=reason_codes,
    )


def _training_paces(confidence="HIGH"):
    return SimpleNamespace(confidence=confidence)


def _performance(has_data=True, extrapolation_ratio=1.32, confidence="medium"):
    return SimpleNamespace(
        has_data=has_data,
        predictions=[
            SimpleNamespace(
                distance_label="5k",
                predicted_time_str="21:00",
                predicted_pace_str="4:12/km",
                confidence=confidence,
                extrapolation_ratio=extrapolation_ratio,
            )
        ] if has_data else [],
    )


async def _premium_access(_db, user_id: str):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


async def _call_coach(
    fake_db: _FakeDB,
    *,
    week_payload: dict | None = None,
    today_payload: dict | None = None,
    training_load=None,
    readiness_decision=None,
    performance=None,
    training_paces=None,
    readiness_result=object(),
    workout_id: str | None = None,
) -> tuple[httpx.Response, dict]:
    captured: dict = {}

    async def _fake_enrich_chat_response(*, user_message, context, conversation_history, user_id):
        captured["context"] = context
        captured["user_message"] = user_message
        captured["conversation_history"] = conversation_history
        captured["user_id"] = user_id
        return "ok", True, {"provider": "test"}

    if hasattr(server.rate_limiter, "requests"):
        server.rate_limiter.requests.clear()

    resolved_goal = SimpleNamespace(
        goal_type="MARATHON",
        mapped_goal=GoalType.marathon,
        cycle_start=date(2026, 8, 1),
        race_date=date(2026, 11, 1),
        target_time_sec=12600,
        target_distance_km=None,
        user_goal_doc={"event_name": "Autumn Marathon"},
    )
    domain_activities = [
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc), distance_m=12000.0),
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc), distance_m=8000.0),
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc), distance_m=14000.0),
    ]

    patches = [
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db, create=True),
        patch("server.get_user_access", AsyncMock(side_effect=_premium_access)),
        patch("server._resolve_canonical_reference_date", return_value=_REFERENCE_DATE),
        patch("server._resolve_goal_v2", AsyncMock(return_value=resolved_goal)),
        patch("server.mongo_garmin_activities_to_domain", side_effect=lambda docs: domain_activities if docs else []),
        patch("server.build_training_load", return_value=training_load or _training_load()),
        patch("server.build_readiness_v2_from_garmin_data", return_value=None if readiness_result is None else readiness_result),
        patch("server.build_readiness_decision", return_value=readiness_decision or _readiness_decision()),
        patch("server.predict_races", return_value=performance or _performance()),
        patch("server.load_canonical_training_paces", AsyncMock(return_value=training_paces or _training_paces())),
        patch("server.get_training_v2_week", AsyncMock(return_value=week_payload or _week_payload())),
        patch("server.get_today_adaptive_session", AsyncMock(return_value=today_payload or _today_payload())),
        patch("coach_context_v2.training_paces_to_api_dict", return_value={"paces": {"easy": {"lower_str": "5:20/km", "upper_str": "5:50/km"}}}),
        patch("llm_coach.enrich_chat_response", side_effect=_fake_enrich_chat_response),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/coach/analyze",
                headers=_bearer(),
                json={"message": "How does this week look?", "language": "en", "workout_id": workout_id},
            )

    return response, captured["context"]


@pytest.mark.asyncio
async def test_coach_context_v2_uses_canonical_authorities_and_prescription_precedence():
    fake_db = _FakeDB()
    response, context = await _call_coach(fake_db)

    assert response.status_code == 200
    assert fake_db.training_plans.find_one_called is False
    assert context["goal"]["objective"] == "Autumn Marathon"
    assert context["today"]["prescription_source"] == "served_snapshot"
    assert context["today"]["served_prescription"]["distance_km"] == 6.4
    assert context["today"]["served_prescription"]["reason_codes"] == ["SNAPSHOT_TODAY"]
    assert context["today"]["planned_session"]["distance_km"] == 8.0
    assert context["today"]["adaptation_action"] == "SHORTEN"
    assert context["today"]["structured_workout"] == {"kind": "structured-today"}

    sessions = {session["day"]: session for session in context["current_week_sessions"]}
    assert sessions["Monday"]["prescription_source"] == "served_snapshot"
    assert sessions["Tuesday"]["prescription_source"] == "planned_memory"
    assert sessions["Tuesday"]["distance_km"] == 7.5
    assert sessions["Tuesday"]["reason_codes"] == ["MEMORY_TUE"]
    assert sessions["Tuesday"]["structured"] == {"kind": "memory-structured"}
    assert sessions["Wednesday"]["prescription_source"] == "unavailable"
    assert sessions["Friday"]["prescription_source"] == "live_planned"

    assert context["training_load"] == {
        "acute_load_7d": 210.0,
        "load_28d": 780.0,
        "chronic_weekly_load": 195.0,
        "acwr": 1.08,
        "status": "balanced",
        "confidence": "high",
        "is_available": True,
        "has_sufficient_history": True,
        "load_change_percent": 7.5,
    }
    assert context["readiness"]["band"] == "CAUTION"
    assert context["readiness"]["data_source"] == "garmin"
    assert context["training_paces"]["confidence"] == "HIGH"
    assert context["training_paces"]["is_available"] is True
    assert context["performance"]["predictions"][0]["confidence"] == "medium"
    assert context["performance"]["predictions"][0]["extrapolation_ratio"] == 1.32
    assert context["performance"]["predictions"][0]["is_strong_extrapolation"] is True


@pytest.mark.asyncio
async def test_coach_context_v2_leaves_missing_data_unavailable():
    fake_db = _FakeDB()
    fake_db.garmin_connections = _Collection([{"user_id": _USER_ID, "connected": False}])
    response, context = await _call_coach(
        fake_db,
        training_load=_training_load(
            acwr=None,
            status="unavailable",
            confidence="none",
            is_available=False,
            has_sufficient_history=False,
            load_change_percent=None,
            acute_load_7d=0.0,
            load_28d=0.0,
            chronic_weekly_load=0.0,
        ),
        readiness_decision=_readiness_decision(
            band="UNAVAILABLE",
            score=None,
            confidence="NONE",
            sufficiency="INSUFFICIENT",
            reason_codes=("READINESS_UNAVAILABLE",),
        ),
        performance=_performance(has_data=False),
        training_paces=_training_paces(confidence="INSUFFICIENT"),
        readiness_result=None,
        today_payload={"status": "no_session", "date": "2026-09-17", "day": "Thursday"},
    )

    assert response.status_code == 200
    assert context["today"]["prescription_source"] == "unavailable"
    assert context["today"]["served_prescription"] is None
    assert context["readiness"] == {
        "band": "UNAVAILABLE",
        "score": None,
        "confidence": "NONE",
        "sufficiency_level": "INSUFFICIENT",
        "reason_codes": ["READINESS_UNAVAILABLE"],
        "data_source": "unavailable",
    }
    assert context["training_load"]["acwr"] is None
    assert context["training_load"]["status"] == "unavailable"
    assert context["training_paces"]["is_available"] is False
    assert context["training_paces"]["confidence"] == "INSUFFICIENT"
    assert context["performance"] == {"has_data": False, "predictions": []}


@pytest.mark.asyncio
async def test_coach_context_v2_enforces_workout_user_isolation():
    fake_db = _FakeDB()
    response, context = await _call_coach(fake_db, workout_id="foreign-workout")

    assert response.status_code == 200
    assert context.get("workout_detail") is None
    assert {"id": "foreign-workout", "user_id": _USER_ID} in fake_db.workouts.find_one_calls


def test_analyze_with_coach_source_uses_v2_authorities_only():
    source = inspect.getsource(server.analyze_with_coach)

    assert "db.training_plans" not in source
    assert 'db.workouts.find_one({"id": request.workout_id, "user_id": user_id})' in source
    assert "load_canonical_training_paces" in source
    assert "compute_training_paces" not in source


def test_system_prompt_coach_declares_v2_authority_rules():
    import llm_coach

    prompt = llm_coach.SYSTEM_PROMPT_COACH
    assert "The Training V2 engine decides the prescription. The Coach only explains it." in prompt
    assert "You have access to ALL their real training data" not in prompt
    assert "Never create a new prescription" in prompt
    assert "Never modify or replace the served prescription" in prompt
