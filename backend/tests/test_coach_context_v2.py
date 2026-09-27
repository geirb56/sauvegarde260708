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
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017/testdb")
os.environ.setdefault("DB_NAME", "testdb")

import server  # noqa: E402
import coach_context_v2  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
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
async def test_coach_context_v2_enforces_workout_user_isolation():
    fake_db = _FakeDB()
    response, context = await _call_coach(fake_db, workout_id="foreign-workout")

    assert response.status_code == 200
    assert context.get("workout_detail") is None
    assert {"id": "foreign-workout", "user_id": _USER_ID} in fake_db.workouts.find_one_calls


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
    cycle_source = inspect.getsource(coach_context_v2._build_cycle_response)
    phase_source = inspect.getsource(coach_context_v2._build_phase_value)

    assert "db.training_plans" not in source
    assert 'db.workouts.find_one({"id": request.workout_id, "user_id": user_id})' in source
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
