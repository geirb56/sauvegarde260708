from __future__ import annotations

import os
import sys
import inspect
import json
from contextlib import contextmanager
from copy import deepcopy
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
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/testdb")
os.environ.setdefault("DB_NAME", "testdb")

import server  # noqa: E402
import coach_context_v2  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from garmin.service import activity_to_workout  # noqa: E402
from training_v2.periodization import build_periodization  # noqa: E402
from training_v2.plan_goal import GoalType, build_plan_goal  # noqa: E402
from training_v2.training_cycle_response import build_cycle_calendar_response  # noqa: E402
from training_v2.training_history import build_training_history  # noqa: E402


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
            if "$gt" in expected and (actual is None or actual <= expected["$gt"]):
                return False
            if "$lt" in expected and (actual is None or actual >= expected["$lt"]):
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
        self.find_projections: list[dict | None] = []
        self.find_calls: list[tuple[dict, dict | None]] = []

    @staticmethod
    def _apply_projection(doc: dict, projection):
        if not projection:
            return dict(doc)
        include_keys = {key for key, value in projection.items() if key != "_id" and value}
        if include_keys:
            projected = {key: doc.get(key) for key in include_keys if key in doc}
            if projection.get("_id", 1):
                projected["_id"] = doc.get("_id")
            return projected
        if projection.get("_id") == 0:
            return {key: value for key, value in doc.items() if key != "_id"}
        return dict(doc)

    async def find_one(self, query, projection=None, sort=None):
        self.find_one_calls.append(dict(query))
        self.find_projections.append(dict(projection) if isinstance(projection, dict) else projection)
        docs = [dict(doc) for doc in self._docs if _matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: doc.get(key), reverse=direction == -1)
        return self._apply_projection(docs[0], projection) if docs else None

    def find(self, query=None, projection=None):
        self.find_projections.append(dict(projection) if isinstance(projection, dict) else projection)
        self.find_calls.append((dict(query or {}), dict(projection) if isinstance(projection, dict) else projection))
        return _Cursor(
            self._apply_projection(dict(doc), projection)
            for doc in self._docs
            if _matches(doc, query or {})
        )

    async def insert_one(self, doc):
        self._docs.append(dict(doc))

    async def count_documents(self, query):
        return sum(1 for doc in self._docs if _matches(doc, query))


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
                "workout_type": "recovery_run",
                "intensity_class": "recovery",
                "distance_km": 4.0,
                "duration_minutes": 28,
                "reason_codes": ["SNAPSHOT_MON"],
                "structured": {"kind": "structured-mon"},
                "modified_from_planned": True,
                "adaptation_action": "KEEP",
                "adaptation_reason_codes": [],
            },
            {
                "user_id": _USER_ID,
                "prescription_id": "thu-id",
                "planned_date": "2026-09-17",
                "day": "thursday",
                "workout_type": "intervals",
                "intensity_class": "quality",
                "distance_km": 11.2,
                "duration_minutes": 64,
                "reason_codes": ["SNAPSHOT_TODAY"],
                "structured": {"kind": "structured-today"},
                "modified_from_planned": False,
                "adaptation_action": "KEEP",
                "adaptation_reason_codes": ["SNAPSHOT_ONLY"],
            },
        ])
        self.training_planned_prescription_memory = _Collection([
            {
                "user_id": _USER_ID,
                "prescription_id": "tue-id",
                "planned_date": "2026-09-15",
                "day": "tuesday",
                "workout_type": "hill_repeats",
                "intensity_class": "quality",
                "distance_km": 5.0,
                "duration_minutes": 31,
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
        self.coach_quota_counters = _Collection([
            {"user_id": _USER_ID, "month_key": "2026-09", "count": 2, "baseline": 1},
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
                    "structured_status": "historical_frozen",
                    "session_modified_from_planned": False,
                    "structured": {"kind": "week-mon"},
                    "actual": {"distance_km": 10.6, "duration_minutes": 61},
                    "estimated_tss": 47.5,
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
                    "structured_status": "historical_frozen",
                    "session_modified_from_planned": None,
                    "structured": {"kind": "week-tue"},
                    "actual": None,
                    "estimated_tss": 39.0,
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
                    "structured_status": "prescription_unavailable",
                    "session_modified_from_planned": None,
                    "structured": None,
                    "actual": None,
                    "estimated_tss": None,
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
                    "actual": {"distance_km": 6.4, "duration_minutes": 35},
                    "estimated_tss": 52.0,
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
                    "structured_status": "future_live",
                    "session_modified_from_planned": None,
                    "structured": {"kind": "week-fri"},
                    "actual": None,
                    "estimated_tss": 71.0,
                    "future_field": {"preserve": True},
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
        "structured_prescription": {"kind": "today-payload"},
        "structured_status": "today_served",
        "readiness": {"band": "CAUTION", "score": 62.0},
        "future_today_field": {"preserve": True},
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


def _performance(has_data=True, extrapolation_ratio=5.2, confidence="medium"):
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
    resolved_goal=None,
    domain_activities=None,
    reference_date: date = _REFERENCE_DATE,
    captured_history_out: list[dict] | None = None,
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

    resolved_goal = resolved_goal or SimpleNamespace(
        goal_type="MARATHON",
        mapped_goal=GoalType.marathon,
        cycle_start=date(2026, 8, 1),
        race_date=date(2026, 11, 1),
        target_time_sec=12600,
        target_distance_km=None,
        user_goal_doc={"event_name": "Autumn Marathon"},
    )
    domain_activities = domain_activities or [
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc), distance_m=12000.0),
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc), distance_m=8000.0),
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 8, 28, 6, 0, tzinfo=timezone.utc), distance_m=14000.0),
    ]

    patches = [
        patch("server.get_user_access", AsyncMock(side_effect=_premium_access)),
        patch("server._resolve_canonical_reference_date", return_value=reference_date),
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

    orig_server_db = getattr(server, "db", None)
    orig_state_db = getattr(server.app.state, "db", None)
    server.db = fake_db
    server.app.state.db = fake_db
    try:
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12]:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/coach/analyze",
                    headers=_bearer(),
                    json={"message": "How does this week look?", "language": "en", "workout_id": workout_id},
                )
    finally:
        server.db = orig_server_db
        server.app.state.db = orig_state_db

    if captured_history_out is not None:
        captured_history_out.extend(captured.get("conversation_history", []))
    return response, captured.get("context")


async def _call_invalid_workout_coach(fake_db: _FakeDB, workout_id: str):
    if hasattr(server.rate_limiter, "requests"):
        server.rate_limiter.requests.clear()
    reserve = AsyncMock(return_value=None)
    llm = AsyncMock(return_value=("ok", True, {}))
    access = AsyncMock(return_value=UserAccess(user_id=_USER_ID, tier=Tier.FREE))
    orig_server_db = getattr(server, "db", None)
    orig_state_db = getattr(server.app.state, "db", None)
    server.db = fake_db
    server.app.state.db = fake_db
    try:
        with (
            patch("server.get_user_access", access),
            patch("server._reserve_free_coach_quota_slot", reserve),
            patch("llm_coach.enrich_chat_response", llm),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/coach/analyze",
                    headers=_bearer(),
                    json={"message": "Analyze this workout", "language": "en", "workout_id": workout_id},
                )
    finally:
        server.db = orig_server_db
        server.app.state.db = orig_state_db
    return response, access, reserve, llm


@pytest.mark.asyncio
async def test_coach_context_v2_uses_canonical_authorities_and_prescription_precedence():
    fake_db = _FakeDB()
    response, context = await _call_coach(fake_db)

    assert response.status_code == 200
    assert fake_db.training_plans.find_one_called is False
    assert context["workout_detail"] is None
    assert "selected_workout_permissions" not in context
    assert context["goal"]["objective"] == "Autumn Marathon"
    assert fake_db.training_prescription_snapshots.find_projections[0] == {"_id": 0}
    assert fake_db.training_planned_prescription_memory.find_projections[0] == {"_id": 0}
    assert context["today"]["prescription_source"] == "served_snapshot"
    assert context["today"]["canonical"] == _today_payload()
    assert context["today"]["canonical"]["served_prescription"] == _today_payload()["served_prescription"]
    assert context["today"]["canonical"]["structured_prescription"] == {"kind": "today-payload"}
    assert context["today"]["canonical"]["future_today_field"] == {"preserve": True}

    sessions = {session["canonical"]["day"]: session for session in context["current_week_sessions"]}
    assert sessions["Monday"]["prescription_source"] == "served_snapshot"
    assert sessions["Tuesday"]["prescription_source"] == "planned_memory"
    assert sessions["Wednesday"]["prescription_source"] == "unavailable"
    assert sessions["Friday"]["prescription_source"] == "live_planned"
    assert sessions["Monday"]["canonical"]["structured_status"] == "historical_frozen"
    assert sessions["Wednesday"]["canonical"]["structured_status"] == "prescription_unavailable"
    assert sessions["Friday"]["canonical"]["structured_status"] == "future_live"
    assert sessions["Monday"]["canonical"]["actual"] == {"distance_km": 10.6, "duration_minutes": 61}
    assert sessions["Friday"]["canonical"]["estimated_tss"] == 71.0
    assert sessions["Friday"]["canonical"]["future_field"] == {"preserve": True}

    expected_sessions = {session["day"]: session for session in _week_payload()["week"]["sessions"]}
    for day, expected_session in expected_sessions.items():
        assert sessions[day]["canonical"] == expected_session

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
    assert context["performance"]["predictions"][0]["extrapolation_ratio"] == 5.2
    assert context["performance"]["predictions"][0]["is_strong_extrapolation"] is True
    expected_cycle = build_cycle_calendar_response(
        build_plan_goal(
            goal_type=GoalType.marathon,
            race_date=date(2026, 11, 1),
            target_distance_km=None,
            target_time_seconds=12600,
            created_from="user",
        ),
        _REFERENCE_DATE,
        race_plan_start_date=date(2026, 8, 1),
        target_time_seconds=12600,
    )
    current_week = next(week for week in expected_cycle.weeks if week.is_current)
    expected_phase = build_periodization(
        build_plan_goal(
            goal_type=GoalType.marathon,
            race_date=date(2026, 11, 1),
            target_distance_km=None,
            target_time_seconds=12600,
            created_from="user",
        ),
        _REFERENCE_DATE,
        race_plan_start_date=date(2026, 8, 1),
    )
    assert context["training_state"]["current_week"] == expected_cycle.cycle.current_week
    assert context["training_state"]["total_weeks"] == expected_cycle.cycle.total_weeks
    assert context["training_state"]["phase"] == expected_phase.phase.value
    assert context["stats_7d"] == {"km": 20.0, "sessions": 2}
    assert context["stats_30d"] == {"km": 34.0, "sessions": 3}


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
    assert context["today"]["canonical"] == {"status": "no_session", "date": "2026-09-17", "day": "Thursday"}
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
@pytest.mark.parametrize(
    ("workout_id", "workout_docs"),
    [
        ("missing-workout", []),
        ("foreign-workout", [{"id": "foreign-workout", "user_id": "other-user"}]),
    ],
)
async def test_coach_analyze_rejects_missing_or_foreign_workout_before_side_effects(workout_id, workout_docs):
    fake_db = _FakeDB()
    fake_db.workouts = _Collection(workout_docs)
    quota_before = [dict(doc) for doc in fake_db.coach_quota_counters._docs]

    response, access, reserve, llm = await _call_invalid_workout_coach(fake_db, workout_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Workout not found"}
    assert fake_db.workouts.find_one_calls == [{"id": workout_id, "user_id": _USER_ID}]
    assert fake_db.conversations._docs == []
    assert fake_db.coach_quota_counters._docs == quota_before
    access.assert_not_awaited()
    reserve.assert_not_awaited()
    llm.assert_not_awaited()


@pytest.mark.asyncio
async def test_coach_context_v2_cycle_calendar_matches_race_cycle_authority():
    fake_db = _FakeDB()
    resolved_goal = SimpleNamespace(
        goal_type="MARATHON",
        mapped_goal=GoalType.marathon,
        cycle_start=date(2026, 9, 1),
        race_date=date(2026, 11, 1),
        target_time_sec=12600,
        target_distance_km=None,
        user_goal_doc={"event_name": "Compressed Marathon"},
    )
    response, context = await _call_coach(fake_db, resolved_goal=resolved_goal)

    assert response.status_code == 200
    expected_cycle = build_cycle_calendar_response(
        build_plan_goal(
            goal_type=GoalType.marathon,
            race_date=date(2026, 11, 1),
            target_distance_km=None,
            target_time_seconds=12600,
            created_from="user",
        ),
        _REFERENCE_DATE,
        race_plan_start_date=date(2026, 9, 1),
        target_time_seconds=12600,
    )
    current_week = next(week for week in expected_cycle.weeks if week.is_current)
    expected_phase = build_periodization(
        build_plan_goal(
            goal_type=GoalType.marathon,
            race_date=date(2026, 11, 1),
            target_distance_km=None,
            target_time_seconds=12600,
            created_from="user",
        ),
        _REFERENCE_DATE,
        race_plan_start_date=date(2026, 9, 1),
    )
    assert context["training_state"]["current_week"] == expected_cycle.cycle.current_week
    assert context["training_state"]["total_weeks"] == expected_cycle.cycle.total_weeks
    assert context["training_state"]["phase"] == expected_phase.phase.value


@pytest.mark.asyncio
async def test_coach_context_v2_cycle_calendar_matches_maintenance_continuous_authority():
    fake_db = _FakeDB()
    resolved_goal = SimpleNamespace(
        goal_type="MAINTENANCE",
        mapped_goal=GoalType.maintenance,
        cycle_start=date(2026, 9, 3),
        race_date=None,
        target_time_sec=None,
        target_distance_km=None,
        user_goal_doc={},
    )
    response, context = await _call_coach(fake_db, resolved_goal=resolved_goal)

    assert response.status_code == 200
    expected_cycle = build_cycle_calendar_response(
        build_plan_goal(
            goal_type=GoalType.maintenance,
            race_date=None,
            target_distance_km=None,
            target_time_seconds=None,
            created_from="user",
        ),
        _REFERENCE_DATE,
        cycle_anchor_date=date(2026, 9, 3),
        target_time_seconds=None,
    )
    current_week = next(week for week in expected_cycle.weeks if week.is_current)
    expected_phase = build_periodization(
        build_plan_goal(
            goal_type=GoalType.maintenance,
            race_date=None,
            target_distance_km=None,
            target_time_seconds=None,
            created_from="user",
        ),
        _REFERENCE_DATE,
        cycle_anchor_date=date(2026, 9, 3),
    )
    assert context["training_state"]["current_week"] == expected_cycle.cycle.current_week
    assert context["training_state"]["total_weeks"] == expected_cycle.cycle.total_weeks
    assert context["training_state"]["phase"] == expected_phase.phase.value


@pytest.mark.asyncio
async def test_coach_context_v2_uses_periodization_phase_during_midweek_transition():
    fake_db = _FakeDB()
    cycle_start = date(2026, 8, 1)
    reference_date = date(2026, 9, 17)
    cycle_response = SimpleNamespace(
        cycle=SimpleNamespace(current_week=7, total_weeks=14),
        weeks=[
            SimpleNamespace(week_number=7, start_date="2026-09-14", end_date="2026-09-20", phase="specific", is_current=True),
        ],
    )
    periodization_snapshot = SimpleNamespace(phase=SimpleNamespace(value="build"))

    with (
        patch("coach_context_v2.build_cycle_calendar_response", return_value=cycle_response),
        patch("coach_context_v2.build_periodization", return_value=periodization_snapshot) as periodization_mock,
        patch("server._resolve_canonical_reference_date", return_value=reference_date),
    ):
        response, context = await _call_coach(
            fake_db,
            resolved_goal=SimpleNamespace(
                goal_type="MARATHON",
                mapped_goal=GoalType.marathon,
                cycle_start=cycle_start,
                race_date=date(2026, 11, 1),
                target_time_sec=12600,
                target_distance_km=None,
                user_goal_doc={"event_name": "Transition Marathon"},
            ),
        )

    assert response.status_code == 200
    assert context["training_state"]["phase"] == "build"
    periodization_mock.assert_called_once()


@pytest.mark.asyncio
async def test_coach_context_v2_stats_match_training_history_v2_running_types():
    fake_db = _FakeDB()
    domain_activities = [
        SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 16, 6, 0, tzinfo=timezone.utc), distance_m=10000.0, duration_s=3000.0),
        SimpleNamespace(activity_type="trail_running", start_time=datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc), distance_m=12000.0, duration_s=4200.0),
        SimpleNamespace(activity_type="treadmill_running", start_time=datetime(2026, 8, 25, 6, 0, tzinfo=timezone.utc), distance_m=8000.0, duration_s=2800.0),
        SimpleNamespace(activity_type="cycling", start_time=datetime(2026, 9, 14, 6, 0, tzinfo=timezone.utc), distance_m=50000.0, duration_s=5400.0),
    ]
    response, context = await _call_coach(fake_db, domain_activities=domain_activities)

    assert response.status_code == 200
    expected_history = build_training_history(domain_activities, _REFERENCE_DATE)
    assert context["stats_7d"] == {
        "km": expected_history.window_7d.distance_km,
        "sessions": expected_history.window_7d.activity_count,
    }
    assert context["stats_30d"] == {
        "km": expected_history.window_30d.distance_km,
        "sessions": expected_history.window_30d.activity_count,
    }
    assert context["stats_7d"] == {"km": 22.0, "sessions": 2}
    assert context["stats_30d"] == {"km": 30.0, "sessions": 3}


def test_analyze_with_coach_source_uses_v2_authorities_only():
    source = inspect.getsource(server.process_coach_message)
    context_source = inspect.getsource(server.build_coach_context_v2)
    analysis_loader_source = inspect.getsource(server.load_scoped_workout_analysis_v2)
    recent_normalizer_source = inspect.getsource(coach_context_v2._normalize_recent_workout)
    cycle_source = inspect.getsource(coach_context_v2._build_cycle_response)
    phase_source = inspect.getsource(coach_context_v2._build_phase_value)

    assert "db.training_plans" not in source
    assert "load_scoped_workout_analysis_v2" in source
    assert "build_workout_analysis_v2" in analysis_loader_source
    assert "build_workout_analysis_v2" not in context_source
    assert "intensity" not in recent_normalizer_source.lower()
    assert "progress" not in recent_normalizer_source.lower()
    assert "workout_analysis_candidate_date_bounds" in analysis_loader_source
    assert "load_canonical_training_paces" in source
    assert "compute_training_paces" not in source
    assert "build_cycle_calendar_response" in cycle_source
    assert "build_periodization" in phase_source
    assert "build_training_history" in context_source
    assert "_count_recent_stats" not in context_source
    assert "stats_28d" not in context_source
    assert "_session_view_from_authority" not in context_source
    assert 'canonical=dict(session)' in context_source
    assert 'canonical=dict(today_payload)' in context_source


def test_system_prompt_coach_declares_v2_authority_rules():
    import llm_coach

    prompt = llm_coach.SYSTEM_PROMPT_COACH
    assert "The Training V2 engine decides the prescription. The Coach only explains it." in prompt
    assert "You have access to ALL their real training data" not in prompt
    assert "Never create a new prescription" in prompt
    assert "Never modify or replace the served prescription" in prompt
    assert "recent_workouts" in prompt
    assert "Workout Analysis V2" in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("analysis_available", [False, True])
async def test_llm_prompts_include_recent_facts_and_block_unsupported_inferences(analysis_available):
    import llm_coach
    from workout_analysis_v2 import build_workout_analysis_v2

    analysis = None
    if analysis_available:
        analysis = build_workout_analysis_v2(
            workout={
                "id": "long-run",
                "name": "Progression Run",
                "date": "2026-09-15T08:00:00Z",
                "type": "run",
                "distance_km": 21.27,
                "duration_minutes": 140,
                "avg_heart_rate": 160,
                "avg_pace_min_km": 6.58,
            },
            historical_workouts=[],
            language="en",
        ).model_dump(mode="json")
        assert analysis["signals"]["intensity"]["available"] is False
        assert analysis["comparison"]["available"] is False

    context = {
        "language": "en",
        "recent_workouts": [
            {
                "id": "short-run",
                "date": "2026-09-14T08:00:00Z",
                "type": "running",
                "name": "Easy Run",
                "distance_km": 10.18,
                "duration_minutes": None,
                "avg_pace_min_km": None,
                "avg_speed_kmh": None,
                "avg_heart_rate": 127,
                "max_heart_rate": None,
                "elevation_gain_m": None,
            }
        ],
        "recent_workouts_coverage": {
            "window_days": 30,
            "start_date_inclusive": "2026-08-19",
            "end_date_inclusive": "2026-09-17",
            "available_count": 1,
            "included_count": 1,
            "max_count": 30,
            "truncated": False,
        },
        "workout_detail": {
            "id": "long-run",
            "name": "Progression Run",
            "date": "2026-09-15T08:00:00Z",
            "type": "run",
            "distance_km": 21.27,
            "duration_minutes": 140,
            "avg_heart_rate": 160,
            "max_heart_rate": None,
            "analysis": analysis,
        },
    }
    captured = {}

    async def _capture_prompts(system_prompt, user_prompt, user_id, context_type):
        captured.update(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            context_type=context_type,
        )
        return "captured", True, {}

    with patch("llm_coach._call_gpt", side_effect=_capture_prompts):
        result = await llm_coach.enrich_chat_response(
            user_message="Compare these runs.",
            context=context,
            conversation_history=[],
            user_id=_USER_ID,
        )

    assert result[0] == "captured"
    prompts = captured["system_prompt"] + "\n" + captured["user_prompt"]
    assert '"distance_km":21.27' in prompts
    assert '"avg_heart_rate":160' in prompts
    assert '"distance_km":10.18' in prompts
    assert '"avg_heart_rate":127' in prompts
    assert "descriptive facts only" in prompts
    assert "do not establish physiological intensity" in prompts
    assert "Never infer threshold, LT1/LT2, easy/hard effort, progress, regression, or physiological efficiency" in prompts
    assert "does not prove progress" in prompts
    assert "available Workout Analysis V2 fields" in prompts
    assert "If analysis is absent" in prompts
    assert "recent_workouts is a bounded selection" in prompts
    assert "if truncated do not claim to have reviewed all sessions" in prompts
    assert "Training V2 remains the sole prescription authority" in prompts
    if analysis_available:
        assert '"available":false' in prompts


@pytest.mark.asyncio
async def test_coach_context_v2_populates_bounded_recent_workouts():
    fake_db = _FakeDB()
    fake_db.garmin_activities = _Collection([
        {
            "external_id": "w-recent-1",
            "user_id": _USER_ID,
            "start_time": "2026-09-15T08:00:00Z",
            "name": "Threshold 8k",
            "activity_type": "running",
            "distance": 8000.0,
            "duration": 2310.0,
            "pace_seconds_per_km": 288.6,
            "average_hr": 162,
            "max_hr": 178,
            "elevation_gain": 45.0,
        },
        {
            "external_id": "w-recent-2",
            "user_id": _USER_ID,
            "start_time": "2026-09-01T07:00:00Z",
            "name": "Track workout",
            "activity_type": "running",
            "distance": 10000.0,
            "duration": 3300.0,
            "average_hr": 140,
            "max_hr": None,
            "elevation_gain": 0.0,
        },
        {
            "external_id": "w-old",
            "user_id": _USER_ID,
            "start_time": "2026-08-10T07:00:00Z",
            "name": "Old run",
            "activity_type": "running",
            "distance": 12000.0,
            "duration": 3900.0,
        },
        {
            "external_id": "w-future",
            "user_id": _USER_ID,
            "start_time": "2026-09-25T07:00:00Z",
            "name": "Future run",
            "activity_type": "running",
            "distance": 15000.0,
            "duration": 4800.0,
        },
        {
            "external_id": "w-other",
            "user_id": "other-user",
            "start_time": "2026-09-14T07:00:00Z",
            "name": "Other user run",
            "activity_type": "running",
            "distance": 5000.0,
            "duration": 1500.0,
        },
    ])

    response, context = await _call_coach(fake_db)
    assert response.status_code == 200
    recent = context.get("recent_workouts", [])
    assert len(recent) == 2

    # Preserves descending date order
    assert recent[0]["id"] == "garmin-w-recent-1"
    assert recent[0]["name"] == "Threshold 8k"
    assert recent[0]["distance_km"] == 8.0
    assert recent[0]["duration_minutes"] == 38.5
    assert recent[0]["avg_pace_display"] == "4:49/km"
    assert "avg_pace_min_km" not in recent[0]
    assert recent[0]["avg_heart_rate"] == 162
    assert recent[0]["max_heart_rate"] == 178
    assert recent[0]["elevation_gain_m"] == 45.0

    # Missing metrics must be None, never 0, and valid 0.0 elevation must be preserved
    assert recent[1]["id"] == "garmin-w-recent-2"
    assert recent[1]["max_heart_rate"] is None
    assert recent[1]["elevation_gain_m"] == 0.0

    # Excluded workouts
    recent_ids = {w["id"] for w in recent}
    assert "garmin-w-old" not in recent_ids
    assert "garmin-w-future" not in recent_ids
    assert "garmin-w-other" not in recent_ids
    assert context["recent_workouts_coverage"] == {
        "window_days": 30,
        "start_date_inclusive": "2026-08-19",
        "end_date_inclusive": "2026-09-17",
        "available_count": 2,
        "included_count": 2,
        "max_count": 30,
        "truncated": False,
    }
    history_query = next(query for query, _ in fake_db.garmin_activities.find_calls if "start_time" in query)
    assert history_query == {
        "user_id": _USER_ID,
        "start_time": {"$gte": "2026-08-19", "$lt": "2026-09-18"},
    }


@pytest.mark.asyncio
async def test_coach_recent_workouts_use_exact_30_inclusive_dates():
    fake_db = _FakeDB()
    fake_db.garmin_activities = _Collection([
        {"external_id": "day-minus-30", "user_id": _USER_ID, "start_time": "2026-08-18T08:00:00Z", "distance": 1000},
        {"external_id": "day-minus-29", "user_id": _USER_ID, "start_time": "2026-08-19T08:00:00Z", "distance": 2000},
        {"external_id": "day-j", "user_id": _USER_ID, "start_time": "2026-09-17T08:00:00Z", "distance": 3000, "elevation_gain": 0},
        {"external_id": "day-plus-1", "user_id": _USER_ID, "start_time": "2026-09-18T08:00:00Z", "distance": 4000},
        {"external_id": "other-user", "user_id": "other-user", "start_time": "2026-09-17T09:00:00Z", "distance": 5000},
    ])

    response, context = await _call_coach(fake_db)

    assert response.status_code == 200
    recent = context["recent_workouts"]
    assert [item["id"] for item in recent] == ["garmin-day-j", "garmin-day-minus-29"]
    assert recent[0]["elevation_gain_m"] == 0.0
    assert context["recent_workouts_coverage"]["available_count"] == 2
    history_query = next(query for query, _ in fake_db.garmin_activities.find_calls if "start_time" in query)
    assert history_query["start_time"] == {
        "$gte": "2026-08-19",
        "$lt": "2026-09-18",
    }
    assert not coach_context_v2._is_valid_recent_workout(
        {"start_time": "2026-08-18T23:59:59Z"},
        _REFERENCE_DATE,
    )
    assert coach_context_v2._is_valid_recent_workout(
        {"start_time": "2026-08-19T00:00:00Z"},
        _REFERENCE_DATE,
    )
    assert coach_context_v2._is_valid_recent_workout(
        {"start_time": "2026-09-17T23:59:59Z"},
        _REFERENCE_DATE,
    )
    assert not coach_context_v2._is_valid_recent_workout(
        {"start_time": "2026-09-18T00:00:00Z"},
        _REFERENCE_DATE,
    )


@pytest.mark.asyncio
async def test_coach_recent_workouts_report_exact_truncated_coverage():
    fake_db = _FakeDB()
    fake_db.garmin_activities = _Collection([
        {
            "external_id": f"activity-{index:02d}",
            "user_id": _USER_ID,
            "start_time": f"2026-09-{17 - index % 17:02d}T{index % 24:02d}:00:00Z",
            "distance": 5000,
        }
        for index in range(35)
    ])

    response, context = await _call_coach(fake_db)

    assert response.status_code == 200
    assert len(context["recent_workouts"]) == 30
    assert context["recent_workouts_coverage"] == {
        "window_days": 30,
        "start_date_inclusive": "2026-08-19",
        "end_date_inclusive": "2026-09-17",
        "available_count": 35,
        "included_count": 30,
        "max_count": 30,
        "truncated": True,
    }
    dates = [item["date"] for item in context["recent_workouts"]]
    assert dates == sorted(dates, reverse=True)


@pytest.mark.asyncio
async def test_coach_context_v2_selected_workout_includes_workout_analysis_v2():
    fake_db = _FakeDB()
    fake_db.workouts = _Collection([
        {
            "id": "w-selected",
            "user_id": _USER_ID,
            "date": "2026-09-12T09:00:00Z",
            "name": "Progression Run",
            "type": "run",
            "distance_km": 12.0,
            "duration_minutes": 60.0,
            "avg_heart_rate": 155,
            "max_heart_rate": 172,
            "elevation_gain_m": 80.0,
        },
        {
            "id": "w-hist-1",
            "user_id": _USER_ID,
            "date": "2026-09-05T09:00:00Z",
            "name": "Earlier Run",
            "type": "run",
            "distance_km": 11.5,
            "duration_minutes": 58.0,
            "avg_heart_rate": 152,
        },
    ])

    response, context = await _call_coach(fake_db, workout_id="w-selected")
    assert response.status_code == 200
    workout_detail = context.get("workout_detail")
    assert workout_detail is not None
    assert workout_detail["id"] == "w-selected"
    assert workout_detail["name"] == "Progression Run"
    assert workout_detail["distance_km"] == 12.0
    assert workout_detail["duration_minutes"] == 60.0
    assert workout_detail["avg_heart_rate"] == 155
    assert workout_detail["max_heart_rate"] == 172
    assert workout_detail["elevation_gain_m"] == 80.0

    analysis = workout_detail.get("analysis")
    assert analysis is not None
    assert analysis["version"] == "v2"
    assert analysis["workout"]["id"] == "w-selected"
    assert "summary" in analysis
    assert "signals" in analysis
    assert "physiology" in analysis
    assert "pacing" in analysis
    assert "comparison" in analysis
    assert "evidence" in analysis
    assert isinstance(analysis["comparison"]["similar"], dict)
    assert analysis["comparison"]["similar"]["available"] is True
    assert "w-hist-1" in analysis["comparison"]["similar"]["workout_ids"]


@pytest.mark.asyncio
async def test_selected_workout_recent_history_uses_strict_prior_timestamp_cutoff():
    selected_start = "2026-09-28T10:00:00Z"
    fake_db = _FakeDB()
    fake_db.workouts = _Collection([
        {
            "id": "garmin-selected-0928",
            "user_id": _USER_ID,
            "date": selected_start,
            "start_time": selected_start,
            "name": "Selected run",
            "type": "run",
            "distance_km": 10.18,
            "duration_minutes": 71,
            "avg_pace_min_km": 6.98,
            "avg_heart_rate": 127,
            "max_heart_rate": 144,
        }
    ])
    fake_db.garmin_activities = _Collection([
        {
            "external_id": "prior-0926",
            "user_id": _USER_ID,
            "start_time": "2026-09-26",
            "distance": 10400,
            "duration": 4100,
            "pace_seconds_per_km": 396,
            "average_hr": 134,
        },
        {
            "external_id": "same-day-before",
            "user_id": _USER_ID,
            "start_time": "2026-09-28T09:59:59Z",
            "distance": 9000,
            "duration": 3600,
            "pace_seconds_per_km": 400,
            "average_hr": 135,
        },
        {
            "external_id": "selected-0928",
            "user_id": _USER_ID,
            "start_time": selected_start,
            "distance": 10180,
            "duration": 4260,
            "pace_seconds_per_km": 419,
            "average_hr": 127,
        },
        {
            "external_id": "same-day-date-only",
            "user_id": _USER_ID,
            "start_time": "2026-09-28",
            "distance": 9000,
            "duration": 3600,
        },
        {
            "external_id": "same-day-after",
            "user_id": _USER_ID,
            "start_time": "2026-09-28T10:00:01Z",
            "distance": 9000,
            "duration": 3600,
        },
        {
            "external_id": "same-day-equal",
            "user_id": _USER_ID,
            "start_time": selected_start,
            "distance": 9000,
            "duration": 3600,
        },
        {
            "external_id": "future-1001",
            "user_id": _USER_ID,
            "start_time": "2026-10-01T08:00:00Z",
            "distance": 9660,
            "duration": 3960,
            "pace_seconds_per_km": 408,
            "average_hr": 141,
        },
    ])

    response, context = await _call_coach(
        fake_db,
        workout_id="garmin-selected-0928",
        reference_date=date(2026, 10, 3),
        domain_activities=[
            SimpleNamespace(
                activity_type="running",
                start_time=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
                distance_m=9660,
            )
        ],
    )

    assert response.status_code == 200
    assert context["workout_detail"]["id"] == "garmin-selected-0928"
    recent = context["recent_workouts"]
    recent_ids = {item["id"] for item in recent}
    assert "garmin-prior-0926" in recent_ids
    assert "garmin-same-day-before" in recent_ids
    assert "garmin-same-day-date-only" not in recent_ids
    assert "garmin-same-day-after" not in recent_ids
    assert "garmin-same-day-equal" not in recent_ids
    assert "garmin-selected-0928" not in recent_ids
    assert "garmin-future-1001" not in recent_ids
    assert context["current_training_context"]["reference_date"] == "2026-10-03"
    assert context["current_training_context"]["temporal_scope"] == "current_only"
    assert context["current_training_context"]["may_include_activity_after_selected_workout"] is True
    assert context["current_training_context"]["historical_selected_workout_evidence"] is False
    assert context["current_training_context"]["stats_7d"]["km"] > 0
    assert context["current_training_context"]["stats_30d"]["km"] > 0
    assert "stats_7d" not in context
    assert "stats_30d" not in context
    assert (
        "may include activity after the selected workout"
        in context["current_training_context"]["description"]
    )
    assert context["recent_workouts_coverage"] == {
        "window_days": 30,
        "start_date_inclusive": "2026-08-30",
        "end_date_inclusive": "2026-09-28",
        "available_count": 2,
        "included_count": 2,
        "max_count": 30,
        "truncated": False,
    }
    assert context["selected_workout_history_cutoff"] == "2026-09-28T10:00:00+00:00"
    assert context["selected_workout_history_cutoff_precision"] == "strict_timestamp_exclusive"


@pytest.mark.parametrize("as_model", [False, True], ids=["dict", "CoachRecentWorkout"])
@pytest.mark.parametrize("selected_timestamp", [True, False], ids=["timestamp", "date_inclusive"])
@pytest.mark.parametrize(
    "candidate_id,candidate_date,expected_exact,expected_date_only",
    [
        ("prior", "2026-09-26", True, True),
        ("before", "2026-09-28T09:59:59Z", True, True),
        ("equal", "2026-09-28T10:00:00Z", False, True),
        ("after", "2026-09-28T10:00:01Z", False, True),
        ("unknown-time", "2026-09-28", False, True),
        ("next-day", "2026-09-29", False, False),
        ("prior-local-day-after-utc", "2026-09-27T23:45:00-12:00", False, True),
        ("prior-local-day-before-utc", "2026-09-27T23:45:00+02:00", True, True),
        ("selected", "2026-09-26", False, False),
        ("selected", "2026-09-28T09:00:00Z", False, False),
        ("invalid", "not-a-date", False, False),
    ],
)
def test_is_before_selected_workout_date_precision(
    as_model, selected_timestamp, candidate_id, candidate_date,
    expected_exact, expected_date_only,
):
    candidate = {"id": candidate_id, "date": candidate_date, "type": "run"}
    if as_model:
        candidate = coach_context_v2.CoachRecentWorkout(**candidate)
    snapshot = deepcopy(candidate)
    selected_datetime = (
        datetime(2026, 9, 28, 10, tzinfo=timezone.utc) if selected_timestamp else None
    )
    assert coach_context_v2._is_before_selected_workout(
        candidate,
        selected_workout_id="selected",
        selected_date=date(2026, 9, 28),
        selected_datetime=selected_datetime,
    ) is (expected_exact if selected_timestamp else expected_date_only)
    assert candidate == snapshot
    projected = coach_context_v2.build_llm_coach_context({
        "workout_detail": {
            "id": "selected",
            "date": "2026-09-28T10:00:00Z" if selected_timestamp else "2026-09-28",
        },
    })
    assert projected["selected_workout_history_cutoff_precision"] == (
        "strict_timestamp_exclusive" if selected_timestamp else "date_inclusive"
    )


_CANONICAL_PACE_PROJECTIONS = [
    ("pace_min_per_km", "pace_display", 6.81, "6:49/km"),
    ("pace_min_per_km_min", "pace_min_display", 5.25, "5:15/km"),
    ("pace_min_per_km_max", "pace_max_display", 6.81, "6:49/km"),
    ("planned_pace_min_per_km", "planned_pace_display", 5.25, "5:15/km"),
    ("actual_pace_min_per_km", "actual_pace_display", 6.81, "6:49/km"),
    ("pace_delta_min_per_km", "pace_delta_display", 0.20, "+0:12/km"),
]


def test_llm_canonical_paces_final_json_is_display_only_and_non_mutating():
    raw_paces = {key: value for key, _, value, _ in _CANONICAL_PACE_PROJECTIONS}
    canonical = {
        "reference_date": "2026-10-03",
        "current_week_sessions": [{
            "canonical": {
                "structured_workout": {"steps": [{**raw_paces, "duration_seconds": 123}]},
                "planned": dict(raw_paces),
                "actual": dict(raw_paces),
            },
        }],
        "today": {"canonical": dict(raw_paces)},
        "workout_detail": {
            "id": "selected",
            "date": "2026-09-28T10:00:00Z",
            "analysis": {"comparison": dict(raw_paces)},
        },
    }
    snapshot = deepcopy(canonical)
    projected = coach_context_v2.build_llm_coach_context(canonical)
    serialized = json.dumps(projected, allow_nan=False)
    reloaded = json.loads(serialized)
    session = reloaded["current_week_sessions"][0]["canonical"]
    expected = {display: text for _, display, _, text in _CANONICAL_PACE_PROJECTIONS}
    assert session["structured_workout"]["steps"] == [{**expected, "duration_seconds": 123}]
    assert session["planned"] == expected
    assert session["actual"] == expected
    assert reloaded["today"]["canonical"] == expected
    assert reloaded["workout_detail"]["analysis"]["comparison"] == expected
    for key, _, raw_value, display in _CANONICAL_PACE_PROJECTIONS:
        assert f'"{key}"' not in serialized
        assert str(raw_value) not in serialized
        assert display in serialized
    assert canonical == snapshot


@pytest.mark.parametrize("raw_key,display_key,unused_value,unused_display", _CANONICAL_PACE_PROJECTIONS)
@pytest.mark.parametrize(
    "invalid", [None, float("nan"), float("inf"), float("-inf"), "invalid", True, {}, []],
)
def test_llm_canonical_invalid_paces_do_not_invent_values(
    raw_key, display_key, unused_value, unused_display, invalid,
):
    canonical = {"today": {"canonical": {raw_key: invalid, "duration_seconds": 123}}}
    projected = coach_context_v2.build_llm_coach_context(canonical)
    serialized = json.dumps(projected, allow_nan=False)
    assert projected["today"]["canonical"] == {"duration_seconds": 123}
    assert f'"{raw_key}"' not in serialized
    assert f'"{display_key}"' not in serialized
    assert canonical["today"]["canonical"][raw_key] is invalid


@pytest.mark.parametrize(
    "raw_value,expected",
    [(0.20, "+0:12/km"), (-0.012, "-0:01/km"), (0.001, "0:00/km"), (-0.001, "0:00/km"), (0, "0:00/km")],
)
def test_llm_canonical_delta_rounding_uses_existing_helper(raw_value, expected):
    projected = coach_context_v2.build_llm_coach_context({
        "today": {"canonical": {"pace_delta_min_per_km": raw_value}},
    })
    serialized = json.dumps(projected, allow_nan=False)
    assert json.loads(serialized)["today"]["canonical"] == {"pace_delta_display": expected}
    assert '"pace_delta_min_per_km"' not in serialized
    assert expected in serialized


def test_llm_pace_formatting_projection_and_grounding_permissions():
    assert coach_context_v2._format_pace_min_km(6.81) == "6:49/km"
    assert coach_context_v2._format_pace_min_km(6.8) == "6:48/km"
    assert coach_context_v2._format_pace_min_km(6.012) == "6:01/km"
    assert coach_context_v2._format_pace_delta_min_km(0.2) == "+0:12/km"
    assert coach_context_v2._format_pace_delta_min_km(-0.012) == "-0:01/km"
    assert coach_context_v2._format_pace_delta_min_km(0.001) == "0:00/km"
    assert coach_context_v2._format_pace_delta_min_km(-0.001) == "0:00/km"

    projected = coach_context_v2.build_llm_coach_context({
        "reference_date": "2026-10-03",
        "recent_workouts": [{"id": "recent", "avg_pace_min_km": 6.81}],
        "workout_detail": {
            "id": "selected",
            "date": "2026-09-28T10:00:00Z",
            "avg_pace_min_km": 6.8,
            "analysis": {
                "signals": {"intensity": {"available": False}},
                "pacing": {"average_pace_min_km": 6.012},
                "comparison": {
                    "avg_pace_min_km": {"current": 6.8, "baseline": 6.6, "difference": 0.2},
                    "similar": {
                        "available": True,
                        "comparable": False,
                        "avg_pace_min_km": 6.6,
                        "pace_difference_min_km": 0.2,
                        "avg_heart_rate": 140,
                        "heart_rate_difference_bpm": -13,
                    },
                },
            },
        },
    })

    assert projected["recent_workouts"][0]["avg_pace_display"] == "6:49/km"
    detail = projected["workout_detail"]
    assert detail["avg_pace_display"] == "6:48/km"
    assert detail["analysis"]["pacing"]["average_pace_display"] == "6:01/km"
    assert "avg_pace_min_km" not in detail["analysis"]["comparison"]
    similar = detail["analysis"]["comparison"]["similar"]
    assert similar["avg_pace_display"] == "6:36/km"
    assert similar["pace_difference_display"] == "+0:12/km"
    permissions = projected["selected_workout_permissions"]
    assert permissions == {
        "intensity_interpretation_allowed": False,
        "raw_hr_is_descriptive_only": True,
        "raw_pace_is_descriptive_only": True,
        "progress_regression_allowed": False,
        "physiological_efficiency_allowed": False,
        "causal_explanation_allowed": False,
        "similar_comparison_available": True,
        "similar_comparable": False,
        "similar_differences_descriptive_only": True,
    }
    available_intensity = coach_context_v2.build_llm_coach_context({
        "workout_detail": {
            "analysis": {
                "signals": {"intensity": {"available": True}},
                "comparison": {"similar": {"available": False, "comparable": False}},
            }
        }
    })["selected_workout_permissions"]
    assert available_intensity["intensity_interpretation_allowed"] is True
    assert available_intensity["raw_hr_is_descriptive_only"] is True
    assert available_intensity["raw_pace_is_descriptive_only"] is True
    serialized = json.dumps(projected)
    for raw_value in ('"avg_pace_min_km"', '"pace_difference_min_km"', "6.81", "6.012", "0.2"):
        assert raw_value not in serialized


def test_llm_training_paces_projection_hides_raw_min_per_km_values():
    projected = coach_context_v2.build_llm_coach_context({
        "language": "en",
        "training_paces": {
            "paces": {
                "easy": {
                    "lower": {
                        "min_per_km": 6.81,
                        "pace_str": "6:49",
                        "km_per_hour": 8.81,
                    },
                    "upper": {
                        "min_per_km": 7.2,
                        "pace_str": "7:12",
                    },
                    "lower_str": "6:49",
                    "upper_str": "7:12",
                },
                "threshold": {
                    "min_per_km": 5.25,
                    "pace_str": "5:15",
                },
            }
        },
    })
    serialized = json.dumps(projected)

    assert '"min_per_km"' not in serialized
    assert "6:49" in serialized
    assert "7:12" in serialized
    assert "5:15" in serialized
    assert "8.81" in serialized
    assert "6.81" not in serialized
    assert projected["training_paces"]["paces"]["easy"]["lower"] == {
        "pace_str": "6:49",
        "km_per_hour": 8.81,
    }
    assert projected["training_paces"]["paces"]["easy"]["upper"] == {"pace_str": "7:12"}
    assert projected["training_paces"]["paces"]["easy"]["lower_str"] == "6:49"
    assert projected["training_paces"]["paces"]["easy"]["upper_str"] == "7:12"
    assert projected["training_paces"]["paces"]["threshold"] == {"pace_str": "5:15"}


@pytest.mark.asyncio
async def test_llm_receives_only_display_paces_and_explicit_interpretation_policy():
    import llm_coach

    context = coach_context_v2.build_llm_coach_context({
        "language": "en",
        "reference_date": "2026-10-03",
        "stats_7d": {"km": 9.66, "sessions": 1},
        "stats_30d": {"km": 30.0, "sessions": 4},
        "current_week_sessions": [{
            "canonical": {
                key: value for key, _, value, _ in _CANONICAL_PACE_PROJECTIONS
            },
        }],
        "training_paces": {
            "paces": {
                "easy": {
                    "lower": {"min_per_km": 6.81, "pace_str": "6:49", "km_per_hour": 8.81},
                    "upper": {"min_per_km": 7.2, "pace_str": "7:12"},
                    "lower_str": "6:49",
                    "upper_str": "7:12",
                },
                "threshold": {"min_per_km": 5.25, "pace_str": "5:15"},
            }
        },
        "recent_workouts": [{"id": "recent", "avg_pace_min_km": 6.81}],
        "workout_detail": {
            "id": "selected",
            "date": "2026-09-28",
            "avg_pace_min_km": 6.8,
            "analysis": {
                "signals": {"intensity": {"available": False}},
                "pacing": {"average_pace_min_km": 6.012},
                "comparison": {
                    "similar": {
                        "available": True,
                        "comparable": False,
                        "avg_pace_min_km": 6.6,
                        "pace_difference_min_km": 0.2,
                        "heart_rate_difference_bpm": -13,
                    }
                },
            },
        },
    })
    captured = {}

    async def _capture(system_prompt, user_prompt, user_id, context_type):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "captured", True, {}

    with patch("llm_coach._call_gpt", side_effect=_capture):
        await llm_coach.enrich_chat_response(
            user_message="Compare this session.",
            context=context,
            conversation_history=[],
            user_id=_USER_ID,
        )

    prompt = captured["system_prompt"] + captured["user_prompt"]
    assert "6:49/km" in prompt
    assert "6:48/km" in prompt
    assert "6:01/km" in prompt
    assert '"avg_pace_min_km"' not in prompt
    assert '"pace_difference_min_km"' not in prompt
    for raw_key, display_key, raw_value, display in _CANONICAL_PACE_PROJECTIONS:
        assert f'"{raw_key}"' not in prompt
        assert str(raw_value) not in prompt
        assert f'"{display_key}":"{display}"' in prompt
    assert "Use pace display strings verbatim" in prompt
    assert '"intensity_interpretation_allowed":false' in prompt
    assert '"progress_regression_allowed":false' in prompt
    assert '"physiological_efficiency_allowed":false' in prompt
    assert '"causal_explanation_allowed":false' in prompt
    assert '"min_per_km"' not in prompt
    assert "6:49" in prompt
    assert "7:12" in prompt
    assert "5:15" in prompt
    assert '"temporal_scope":"current_only"' in prompt
    assert '"reference_date":"2026-10-03"' in prompt
    assert '"historical_selected_workout_evidence":false' in prompt
    assert '"may_include_activity_after_selected_workout":true' in prompt


@pytest.mark.asyncio
async def test_coach_conversation_history_is_scoped_by_workout_and_general_chat():
    reference = datetime(2026, 9, 20, tzinfo=timezone.utc)
    fake_db = _FakeDB()
    fake_db.workouts = _Collection([
        {
            "id": "workout-a",
            "user_id": _USER_ID,
            "date": "2026-09-18T08:00:00Z",
            "name": "Workout A",
            "type": "run",
            "distance_km": 10,
            "duration_minutes": 60,
        },
        {
            "id": "workout-b",
            "user_id": _USER_ID,
            "date": "2026-09-19T08:00:00Z",
            "name": "Workout B",
            "type": "run",
            "distance_km": 10,
            "duration_minutes": 60,
        },
    ])
    fake_db.conversations = _Collection([
        {"user_id": _USER_ID, "role": "user", "content": "A discussion", "workout_id": "workout-a", "timestamp": "2026-09-19T10:00:00Z"},
        {"user_id": _USER_ID, "role": "assistant", "content": "A response", "workout_id": "workout-a", "timestamp": "2026-09-19T10:01:00Z"},
        {"user_id": _USER_ID, "role": "user", "content": "B discussion", "workout_id": "workout-b", "timestamp": "2026-09-19T11:00:00Z"},
        {"user_id": _USER_ID, "role": "assistant", "content": "B response", "workout_id": "workout-b", "timestamp": "2026-09-19T11:01:00Z"},
        {"user_id": _USER_ID, "role": "user", "content": "General discussion", "workout_id": None, "timestamp": "2026-09-19T12:00:00Z"},
        {"user_id": _USER_ID, "role": "assistant", "content": "General response", "workout_id": None, "timestamp": "2026-09-19T12:01:00Z"},
    ])

    for workout_id, expected, forbidden in (
        ("workout-a", {"A discussion", "A response"}, {"B discussion", "B response", "General discussion"}),
        ("workout-b", {"B discussion", "B response"}, {"A discussion", "A response", "General discussion"}),
        (None, {"General discussion", "General response"}, {"A discussion", "A response", "B discussion", "B response"}),
    ):
        captured_history: list[dict] = []
        response, _context = await _call_coach(
            fake_db,
            workout_id=workout_id,
            reference_date=date(2026, 9, 20),
            captured_history_out=captured_history,
        )
        assert response.status_code == 200
        contents = {item["content"] for item in captured_history}
        assert expected <= contents
        assert forbidden.isdisjoint(contents)

    with patch("server.db", fake_db):
        full_history = await server.get_conversation_history(user={"id": _USER_ID})
    assert {"A discussion", "B discussion", "General discussion"} <= {
        item["content"] for item in full_history
    }


@pytest.mark.asyncio
async def test_load_scoped_workout_analysis_v2_enriches_minimal_garmin_workout():
    from workout_analysis_v2_service import load_scoped_workout_analysis_v2

    # 1. Real activity_to_workout execution on realistic normalized Garmin activity
    raw_garmin_activity = {
        "external_id": "987654",
        "activity_type": "running",
        "name": "Morning Run",
        "start_time": "2026-09-15T08:00:00Z",
        "distance": 10000.0,
        "duration": 3000.0,
        "pace_seconds_per_km": 300.0,
        "avg_hr": 148,
    }
    derived_workout = activity_to_workout(raw_garmin_activity, _USER_ID)
    assert derived_workout is not None
    assert derived_workout["id"] == "garmin-987654"
    assert derived_workout["user_id"] == _USER_ID
    assert derived_workout["data_source"] == "garmin"
    assert derived_workout["distance_km"] == 10.0
    assert derived_workout["duration_minutes"] == 50
    assert derived_workout["avg_heart_rate"] == 148
    # Derived workout intentionally lacks deep Garmin fields
    assert "max_heart_rate" not in derived_workout
    assert "elevation_gain_m" not in derived_workout
    assert "avg_speed_kmh" not in derived_workout
    assert "avg_cadence_spm" not in derived_workout

    fake_db = _FakeDB()
    # Stored in workouts collection as derived product layer
    fake_db.workouts = _Collection([dict(derived_workout)])

    # Rich ingestion source in garmin_activities
    fake_db.garmin_activities = _Collection([
        {
            "external_id": "987654",
            "user_id": _USER_ID,
            "start_time": "2026-09-15T08:00:00Z",
            "distance": 10000.0,
            "duration": 3000.0,
            "avg_hr": 148,
            "garmin_activity": {
                "activity_id": "987654",
                "average_hr": 148,
                "max_hr": 172,
                "elevation_gain": 0.0,  # true zero
                "average_speed_mps": 3.33,
                "average_run_cadence": 168.0,
                "has_splits": True,
            },
            "raw_payload": {
                "elevationGain": 0.0,
                "maxHR": 172,
                "averageSpeed": 3.33,
            },
        }
    ])

    result = await load_scoped_workout_analysis_v2(
        db=fake_db,
        user_id=_USER_ID,
        workout_id="garmin-987654",
        language="en",
    )
    assert result is not None
    workout, analysis = result

    # 2. Loader retains workout product identity
    assert workout["id"] == "garmin-987654"
    assert workout["user_id"] == _USER_ID
    assert workout["data_source"] == "garmin"

    # 4. Enriched in-memory copy contains available Garmin facts
    assert workout["max_heart_rate"] == 172
    assert workout["elevation_gain_m"] == 0.0  # true zero preserved
    assert workout["avg_speed_kmh"] == 11.99
    assert workout["avg_cadence_spm"] == 168.0

    # 5. Absent fields remain absent
    assert workout.get("effort_zone_distribution") is None
    assert workout.get("km_splits") is None
    assert workout.get("split_analysis") is None

    # 6. No physiological data is invented
    assert workout.get("vo2max") is None
    assert workout.get("lactate_threshold") is None

    # 7. Original db.workouts document is NOT mutated or persisted with enrichment
    original_stored_doc = fake_db.workouts._docs[0]
    assert original_stored_doc.get("max_heart_rate") is None
    assert original_stored_doc.get("elevation_gain_m") is None
    assert original_stored_doc.get("avg_speed_kmh") is None
    assert original_stored_doc.get("avg_cadence_spm") is None

    # Analysis incorporates enriched facts
    assert analysis is not None
    assert analysis.evidence.has_cadence is True
    assert analysis.evidence.has_elevation is True
    assert analysis.evidence.has_heart_rate is True
    assert analysis.physiology.max_hr == 172
    assert analysis.pacing.average_speed_kmh == 11.99


@pytest.mark.asyncio
async def test_load_scoped_workout_analysis_v2_no_matching_garmin_source():
    from workout_analysis_v2_service import load_scoped_workout_analysis_v2

    raw_garmin_activity = {
        "external_id": "777888",
        "activity_type": "running",
        "name": "Tempo Run",
        "start_time": "2026-09-14T07:00:00Z",
        "distance": 8000.0,
        "duration": 2400.0,
        "pace_seconds_per_km": 300.0,
        "avg_hr": 155,
    }
    derived_workout = activity_to_workout(raw_garmin_activity, _USER_ID)
    assert derived_workout is not None

    fake_db = _FakeDB()
    fake_db.workouts = _Collection([dict(derived_workout)])
    fake_db.garmin_activities = _Collection([])  # No matching Garmin source document

    result = await load_scoped_workout_analysis_v2(
        db=fake_db,
        user_id=_USER_ID,
        workout_id="garmin-777888",
        language="en",
    )
    assert result is not None
    workout, analysis = result

    # Minimal workout preserved without crash
    assert workout["id"] == "garmin-777888"
    assert workout["distance_km"] == 8.0
    assert workout.get("max_heart_rate") is None
    assert workout.get("elevation_gain_m") is None
    assert workout.get("avg_cadence_spm") is None

    # Analysis partially available based on minimal workout fields
    assert analysis is not None
    assert analysis.evidence.has_cadence is False
    assert analysis.evidence.has_elevation is False
    assert analysis.evidence.has_heart_rate is True


@pytest.mark.asyncio
async def test_load_scoped_workout_analysis_v2_user_scoping_no_cross_contamination():
    from workout_analysis_v2_service import load_scoped_workout_analysis_v2

    raw_garmin_activity = {
        "external_id": "111111",
        "activity_type": "running",
        "name": "Garmin Activity",
        "start_time": "2026-09-15T08:00:00Z",
        "distance": 8000.0,
        "duration": 2700.0,
        "pace_seconds_per_km": 337.5,
        "avg_hr": 140,
    }
    derived_workout = activity_to_workout(raw_garmin_activity, _USER_ID)
    assert derived_workout is not None

    fake_db = _FakeDB()
    fake_db.workouts = _Collection([dict(derived_workout)])
    # Activity exists in garmin_activities with matching external_id but belongs to other-user
    fake_db.garmin_activities = _Collection([
        {
            "external_id": "111111",
            "user_id": "other-user",
            "start_time": "2026-09-15T08:00:00Z",
            "garmin_activity": {
                "max_hr": 195,
                "elevation_gain": 300.0,
                "average_run_cadence": 180.0,
            },
        }
    ])

    result = await load_scoped_workout_analysis_v2(
        db=fake_db,
        user_id=_USER_ID,
        workout_id="garmin-111111",
        language="en",
    )
    assert result is not None
    workout, analysis = result
    # Must NOT leak other user's facts
    assert workout.get("max_heart_rate") is None
    assert workout.get("elevation_gain_m") is None
    assert workout.get("avg_cadence_spm") is None

    # Foreign workout requested by other-user returns None (404)
    foreign_result = await load_scoped_workout_analysis_v2(
        db=fake_db,
        user_id="other-user",
        workout_id="garmin-111111",
        language="en",
    )
    assert foreign_result is None


@pytest.mark.asyncio
async def test_coach_analyze_with_minimal_garmin_workout_pipeline():
    raw_garmin_activity = {
        "external_id": "real-pipeline-1",
        "activity_type": "running",
        "name": "Morning Run",
        "start_time": "2026-09-15T07:30:00Z",
        "distance": 11200.0,
        "duration": 3300.0,
        "pace_seconds_per_km": 294.6,
        "avg_hr": 152,
    }
    derived_workout = activity_to_workout(raw_garmin_activity, _USER_ID)
    assert derived_workout is not None

    fake_db = _FakeDB()
    fake_db.workouts = _Collection([dict(derived_workout)])
    # Full native observation in garmin_activities
    fake_db.garmin_activities = _Collection([
        {
            "external_id": "real-pipeline-1",
            "user_id": _USER_ID,
            "start_time": "2026-09-15T07:30:00Z",
            "distance": 11200.0,
            "duration": 3300.0,
            "avg_hr": 152,
            "garmin_activity": {
                "activity_id": "real-pipeline-1",
                "average_hr": 152,
                "max_hr": 178,
                "elevation_gain": 65.0,
                "average_speed_mps": 3.394,
                "average_run_cadence": 170.0,
            },
            "raw_payload": {
                "elevationGain": 65.0,
                "maxHR": 178,
                "averageSpeed": 3.394,
            },
        }
    ])

    response, context = await _call_coach(fake_db, workout_id="garmin-real-pipeline-1")
    assert response.status_code == 200
    detail = context.get("workout_detail")
    assert detail is not None
    assert detail["id"] == "garmin-real-pipeline-1"
    assert detail["max_heart_rate"] == 178
    assert detail["elevation_gain_m"] == 65.0
    assert detail["avg_speed_kmh"] == 12.22

    analysis = detail.get("analysis")
    assert analysis is not None
    assert analysis["evidence"]["has_elevation"] is True
    assert analysis["evidence"]["has_cadence"] is True
    assert analysis["physiology"]["max_hr"] == 178
