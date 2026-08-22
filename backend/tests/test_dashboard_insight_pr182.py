"""PR182 — Dashboard insight visible authority must be DomainActivity."""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import dashboard_insight_cache as _dic

os.environ.setdefault("JWT_SECRET_KEY", "integration-test-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from server import auth_user  # noqa: E402


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=reverse)
        return self

    async def to_list(self, length: Optional[int] = None) -> List[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs = list(docs or [])

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> _Cursor:
        def _match(doc: dict) -> bool:
            for key, value in (query or {}).items():
                if isinstance(value, dict):
                    continue
                if doc.get(key) != value:
                    return False
            return True

        return _Cursor([dict(doc) for doc in self._docs if _match(doc)])


class _FakeDB:
    def __init__(
        self,
        *,
        workouts: Optional[List[dict]] = None,
        garmin_activities: Optional[List[dict]] = None,
    ) -> None:
        self.workouts = _Collection(workouts)
        self.garmin_activities = _Collection(garmin_activities)


def _override_user(user_id: str):
    async def _inner():
        return {"id": user_id}

    return _inner


def _bearer(user_id: str, email: str = "test@example.com") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _garmin_act(
    user_id: str,
    *,
    days_ago: int,
    km: float,
    minutes: float,
    activity_type: str = "running",
) -> dict:
    act_date = date.today() - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": activity_type,
        "start_time": f"{act_date.isoformat()}T08:00:00+00:00",
        "distance_m": km * 1000.0,
        "duration_s": minutes * 60.0,
    }


async def _get_insight(fake_db: _FakeDB, user_id: str, run_index_payload: Optional[dict] = None) -> dict:
    _dic._cache.clear()
    server.app.dependency_overrides[auth_user] = _override_user(user_id)
    payload = run_index_payload if run_index_payload is not None else {"run_index": 612, "confidence_score": 78}
    try:
        with (
            patch.object(server.app.state, "db", fake_db, create=True),
            patch("server.calculate_run_index_from_domain", return_value=payload),
            patch("server.upsert_run_index_snapshot", new=AsyncMock(return_value=None)),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app),
                base_url="http://test",
            ) as client:
                response = await client.get("/api/dashboard/insight", headers=_bearer(user_id))
    finally:
        server.app.dependency_overrides.clear()
        _dic._cache.clear()

    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_pr182_week_stats_use_domain_activity_only():
    user_id = "pr182-week"
    fake_db = _FakeDB(
        workouts=[{"user_id": user_id, "date": date.today().isoformat(), "distance_km": 99.0}],
        garmin_activities=[
            _garmin_act(user_id, days_ago=0, km=10.0, minutes=50),
            _garmin_act(user_id, days_ago=3, km=6.0, minutes=32, activity_type="trail_running"),
            _garmin_act(user_id, days_ago=5, km=4.0, minutes=24, activity_type="cycling"),
            _garmin_act(user_id, days_ago=8, km=12.0, minutes=60),
        ],
    )

    payload = await _get_insight(fake_db, user_id)

    assert payload["week"]["sessions"] == 2
    assert payload["week"]["volume_km"] == 16.0
    assert payload["week"]["actual_duration_minutes"] == 82
    assert payload["week"]["load_signal"] == "low"
    assert payload["recovery_score"] is None


@pytest.mark.asyncio
async def test_pr182_month_stats_use_domain_activity_with_previous_30d_comparison():
    user_id = "pr182-month"
    current_dates = [2, 9, 18]
    previous_dates = [31, 36]
    fake_db = _FakeDB(
        garmin_activities=[
            *[_garmin_act(user_id, days_ago=d, km=10.0, minutes=50) for d in current_dates],
            *[_garmin_act(user_id, days_ago=d, km=5.0, minutes=27) for d in previous_dates],
            _garmin_act(user_id, days_ago=45, km=7.0, minutes=39, activity_type="cycling"),
        ]
    )

    payload = await _get_insight(fake_db, user_id)
    expected_active_weeks = len(
        {
            (dt.isocalendar()[0], dt.isocalendar()[1])
            for dt in ((date.today() - timedelta(days=d)) for d in current_dates)
        }
    )

    assert payload["month"]["volume_km"] == 30.0
    assert payload["month"]["active_weeks"] == expected_active_weeks
    assert payload["month"]["trend"] == "up"


@pytest.mark.asyncio
async def test_pr182_no_activity_returns_true_zeroes():
    user_id = "pr182-empty"
    payload = await _get_insight(_FakeDB(), user_id)

    assert payload["week"]["sessions"] == 0
    assert payload["week"]["volume_km"] == 0
    assert payload["week"]["actual_duration_minutes"] == 0
    assert payload["month"]["volume_km"] == 0
    assert payload["month"]["active_weeks"] == 0
    assert payload["month"]["trend"] == "stable"


@pytest.mark.asyncio
async def test_pr182_visible_dashboard_stats_ignore_db_workouts_when_sources_diverge():
    user_id = "pr182-diverge"
    fake_db = _FakeDB(
        workouts=[
            {"user_id": user_id, "date": (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat(), "distance_km": 70.0},
            {"user_id": user_id, "date": (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat(), "distance_km": 20.0},
        ],
        garmin_activities=[_garmin_act(user_id, days_ago=1, km=8.0, minutes=42)],
    )

    payload = await _get_insight(fake_db, user_id)

    assert payload["week"]["sessions"] == 1
    assert payload["week"]["volume_km"] == 8.0
    assert payload["month"]["volume_km"] == 8.0


@pytest.mark.asyncio
async def test_pr182_run_index_insufficient_passthrough_unchanged():
    user_id = "pr182-runindex"
    payload = await _get_insight(
        _FakeDB(garmin_activities=[]),
        user_id,
        run_index_payload={"status": "insufficient", "run_index": None, "confidence_score": 0},
    )

    assert payload["run_index"]["status"] == "insufficient"
    assert payload["run_index"]["run_index"] is None


def test_pr182_static_audit_dashboard_insight_no_visible_db_workouts_dependency():
    source = open(os.path.join(_BACKEND_DIR, "server.py"), "r", encoding="utf-8").read()
    start = source.index('@api_router.get("/dashboard/insight")')
    end = source.find("\n@api_router.get(", start + 1)
    if end == -1:
        end = len(source)
    segment = source[start:end]
    assert "db.workouts.find" not in segment
    assert "load_garmin_domain_activities" in segment
