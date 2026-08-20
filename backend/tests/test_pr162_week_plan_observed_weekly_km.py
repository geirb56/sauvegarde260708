"""
PR #162 — week-plan stops using compute_current_weekly_km runtime consumer.

Scope:
- A/B/C: /api/training/week-plan sets context["weekly_km"] from observed
  running volume (km_28_running / 4.0), including zero-history semantics.
- D/E/F: WeeklyTarget V2 prescription guard and reprise/TSS behavior stay valid.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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

import llm_coach as _llm_coach  # noqa: E402
import server  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from llm_coach import generate_cycle_week  # noqa: E402
from training_engine import compute_current_weekly_km  # noqa: E402

pytestmark = pytest.mark.asyncio

_USER_ID = "pr162-test-user"
_START_DATE = datetime(2026, 6, 1, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs or [])

    async def to_list(self, length=None):
        if isinstance(length, int) and length >= 0:
            return list(self._docs[:length])
        return list(self._docs)


class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    async def find_one(self, query, projection=None):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                return dict(doc)
        return None

    def find(self, query=None, projection=None):
        docs = list(self._docs)
        for key, expected in (query or {}).items():
            if isinstance(expected, dict) and "$gte" in expected:
                gte = expected["$gte"]
                docs = [d for d in docs if str(d.get(key, "")) >= str(gte)]
            else:
                docs = [d for d in docs if d.get(key) == expected]
        return _Cursor(docs)

    async def update_one(self, *args, **kwargs):
        return None

    async def create_index(self, *args, **kwargs):
        return None

    async def count_documents(self, query):
        return 0


class _FakeDB:
    def __init__(self, workouts):
        self.training_cycles = _Collection([{
            "user_id": _USER_ID,
            "goal": "SEMI",
            "start_date": _START_DATE,
            "updated_at": _START_DATE,
        }])
        self.user_goals = _Collection([{
            "user_id": _USER_ID,
            "event_name": "Semi test",
            "event_date": datetime(2026, 10, 1, tzinfo=timezone.utc),
        }])
        self.workouts = _Collection(workouts)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _bearer():
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, "pr162@test.com")}


async def _mock_get_user_access(db, user_id):
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _mock_generate_cycle_week():
    async def _inner(context, phase, goal, user_id="unknown", target_load=None, **kwargs):
        return {"sessions": [], "weekly_km": context.get("weekly_km"), "total_tss": None}, True, {"source": "mock"}

    return _inner


def _fixed_weekly_target(*, basis="distance", target_km=42.0, target_duration_minutes=None, continuity_state="normal"):
    return SimpleNamespace(
        target_basis=basis,
        target_km=target_km,
        target_duration_minutes=target_duration_minutes,
        continuity_state=continuity_state,
    )


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


@pytest_asyncio.fixture
async def client_factory():
    clients = []
    patches = []

    async def _make(workouts, *, weekly_target=None):
        fake_db = _FakeDB(workouts)
        active = [
            patch.object(server, "db", fake_db),
            patch("server.get_user_access", AsyncMock(side_effect=_mock_get_user_access)),
            patch("server.generate_cycle_week", _mock_generate_cycle_week()),
            patch(
                "training_v2.week_plan_bridge.build_weekly_target_from_workouts",
                return_value=weekly_target or _fixed_weekly_target(),
            ),
        ]
        for p in active:
            p.start()
            patches.append(p)
        ac = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        )
        clients.append(ac)
        return ac

    try:
        yield _make
    finally:
        for ac in clients:
            await ac.aclose()
        for p in reversed(patches):
            p.stop()


async def test_a_positive_history_observed_matches_km28_over_4_and_legacy_when_running(client_factory):
    workouts = [
        {"user_id": _USER_ID, "date": _now_iso(2), "type": "run", "distance_km": 8},
        {"user_id": _USER_ID, "date": _now_iso(6), "sport_type": "running", "distance": 12000},
        {"user_id": _USER_ID, "date": _now_iso(13), "activity_type": "run", "distance_km": 10},
        {"user_id": _USER_ID, "date": _now_iso(20), "type": "ride", "distance_km": 100},
    ]
    expected_observed = (8 + 12 + 10) / 4.0
    expected_legacy = compute_current_weekly_km(workouts)

    client = await client_factory(workouts)
    resp = await client.get("/api/training/week-plan", headers=_bearer())

    assert resp.status_code == 200
    body = resp.json()
    observed = body["context"]["weekly_km"]
    assert observed == pytest.approx(expected_observed)
    assert observed == pytest.approx(expected_legacy)


async def test_b_zero_history_observed_weekly_km_is_zero_not_20(client_factory):
    client = await client_factory([])
    resp = await client.get("/api/training/week-plan", headers=_bearer())

    assert resp.status_code == 200
    observed = resp.json()["context"]["weekly_km"]
    assert observed == 0.0
    assert observed != 20


async def test_c_non_running_only_observed_weekly_km_is_zero(client_factory):
    workouts = [
        {"user_id": _USER_ID, "date": _now_iso(1), "type": "ride", "distance_km": 40},
        {"user_id": _USER_ID, "date": _now_iso(4), "type": "swim", "distance_km": 2},
        {"user_id": _USER_ID, "date": _now_iso(7), "type": "yoga", "distance_km": 0},
    ]
    client = await client_factory(workouts)
    resp = await client.get("/api/training/week-plan", headers=_bearer())

    assert resp.status_code == 200
    assert resp.json()["context"]["weekly_km"] == 0.0


def test_d_distance_v2_target_protected_with_weekly_km_zero_no_legacy_calls():
    compute_calls = []
    guard_calls = []

    original_compute = _llm_coach.compute_target_km
    original_guard = _llm_coach.apply_resume_guard

    def spy_compute(weekly_km, goal, phase):
        compute_calls.append((weekly_km, goal, phase))
        return original_compute(weekly_km, goal, phase)

    def spy_guard(target, recent, chronic):
        guard_calls.append((target, recent, chronic))
        return original_guard(target, recent, chronic)

    _llm_coach.compute_target_km = spy_compute
    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = {
            "weekly_km": 0.0,
            "km_7": 0.0,
            "target_km_protected": 36.0,
            "paces": {"z1": "7:00-7:30", "z2": "6:00-6:30", "z3": "5:30-5:45", "z4": "5:00-5:15"},
        }
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx,
                phase="build",
                goal="SEMI",
                user_id="pr162-d",
                sessions_per_week=4,
            )
        )
    finally:
        _llm_coach.compute_target_km = original_compute
        _llm_coach.apply_resume_guard = original_guard

    assert success
    assert compute_calls == []
    assert guard_calls == []
    assert plan["weekly_km"] == pytest.approx(36.0)


def test_e_duration_reprise_valid_with_weekly_km_zero_no_fictive_baseline():
    ctx = {
        "weekly_km": 0.0,
        "km_7": 0.0,
        "target_km_protected": None,
        "target_duration_minutes": 120,
        "training_state": "deep_reprise",
        "prior_weekly_km": 0.0,
        "reprise_active_weeks": 0,
        "paces": {"z1": "7:00-7:30", "z2": "6:00-6:30", "z3": "5:30-5:45", "z4": "5:00-5:15"},
    }

    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx,
            phase="build",
            goal="SEMI",
            user_id="pr162-e",
            sessions_per_week=4,
        )
    )

    assert success
    assert plan["reprise"] is True
    assert plan["weekly_minutes"] is not None and plan["weekly_minutes"] > 0
    assert "cible:" not in plan["advice"]


def test_f_tss_doctrine_unchanged_active_none_rest_zero_total_none():
    ctx = {
        "weekly_km": 0.0,
        "km_7": 0.0,
        "target_km_protected": 30.0,
        "paces": {"z1": "7:00-7:30", "z2": "6:00-6:30", "z3": "5:30-5:45", "z4": "5:00-5:15"},
    }
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx,
            phase="build",
            goal="SEMI",
            user_id="pr162-f",
            sessions_per_week=4,
        )
    )

    assert success
    assert plan["total_tss"] is None
    active_tss = [s["estimated_tss"] for s in plan["sessions"] if s["type"] != "rest"]
    rest_tss = [s["estimated_tss"] for s in plan["sessions"] if s["type"] == "rest"]
    assert all(v is None for v in active_tss)
    assert all(v == 0 for v in rest_tss)
