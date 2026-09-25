from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "workout-analysis-v2-test-secret-32chars!!")
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
import workout_analysis_v2  # noqa: E402
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
        self._docs.sort(key=lambda doc: doc.get(key, ""), reverse=reverse)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = list(docs or [])

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        return all(doc.get(k) == v for k, v in query.items())

    def find(self, query: dict | None = None, projection: dict | None = None) -> _Cursor:
        q = query or {}
        docs = [dict(doc) for doc in self._docs if self._matches(doc, q)]
        if projection:
            docs = [{k: v for k, v in doc.items() if projection.get(k, 1)} for doc in docs]
        return _Cursor(docs)

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        for doc in self._docs:
            if self._matches(doc, query):
                result = dict(doc)
                if projection:
                    result = {k: v for k, v in result.items() if projection.get(k, 1)}
                return result
        return None

    async def insert_one(self, doc: dict):
        self._docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._matches(doc, query))

    async def create_index(self, *args, **kwargs) -> None:
        return None


def _workout(
    workout_id: str,
    *,
    user_id: str,
    date: str,
    workout_type: str = "run",
    distance_km: float,
    duration_minutes: int,
    avg_heart_rate: int | None = None,
    max_heart_rate: int | None = None,
    avg_pace_min_km: float | None = None,
    avg_speed_kmh: float | None = None,
    effort_zone_distribution: dict | None = None,
    km_splits: list[dict] | None = None,
    split_analysis: dict | None = None,
    hr_analysis: dict | None = None,
) -> dict:
    return {
        "id": workout_id,
        "user_id": user_id,
        "date": date,
        "type": workout_type,
        "name": workout_id,
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
        "avg_heart_rate": avg_heart_rate,
        "max_heart_rate": max_heart_rate,
        "avg_pace_min_km": avg_pace_min_km,
        "avg_speed_kmh": avg_speed_kmh,
        "effort_zone_distribution": effort_zone_distribution,
        "km_splits": km_splits or [],
        "split_analysis": split_analysis or {},
        "hr_analysis": hr_analysis or {},
        "data_source": "garmin",
    }


class _FakeDB:
    CURRENT_ID = "run-current"
    NO_HR_ID = "run-nohr"
    NO_BASELINE_ID = "swim-no-baseline"
    ISOLATED_ID = "run-isolated"
    OTHER_USER_ID = "user-b-run"

    def __init__(self) -> None:
        self.workouts = _Collection([
            _workout(
                self.CURRENT_ID,
                user_id="user-a",
                date="2024-01-10T07:00:00+00:00",
                distance_km=10.0,
                duration_minutes=60,
                avg_heart_rate=150,
                max_heart_rate=170,
                avg_pace_min_km=6.0,
                effort_zone_distribution={"z1": 20, "z2": 50, "z3": 20, "z4": 10, "z5": 0},
                km_splits=[
                    {"km": 1, "pace_min_km": 5.9, "pace_str": "5:54"},
                    {"km": 2, "pace_min_km": 6.0, "pace_str": "6:00"},
                    {"km": 3, "pace_min_km": 6.1, "pace_str": "6:06"},
                ],
                split_analysis={
                    "fastest_split_pace": 5.9,
                    "slowest_split_pace": 6.1,
                    "pace_drop": 0.2,
                    "negative_split": False,
                    "consistency_score": 92,
                },
                hr_analysis={"hr_drift": 6},
            ),
            _workout(
                "run-prev-1",
                user_id="user-a",
                date="2024-01-05T07:00:00+00:00",
                distance_km=8.0,
                duration_minutes=48,
                avg_heart_rate=145,
                max_heart_rate=165,
                avg_pace_min_km=6.1,
            ),
            _workout(
                "run-prev-2",
                user_id="user-a",
                date="2024-01-02T07:00:00+00:00",
                distance_km=12.0,
                duration_minutes=72,
                avg_heart_rate=148,
                max_heart_rate=168,
                avg_pace_min_km=6.0,
            ),
            _workout(
                "run-future",
                user_id="user-a",
                date="2024-01-12T07:00:00+00:00",
                distance_km=25.0,
                duration_minutes=140,
                avg_heart_rate=165,
                max_heart_rate=182,
                avg_pace_min_km=5.5,
            ),
            _workout(
                "cycle-prev",
                user_id="user-a",
                date="2024-01-06T07:00:00+00:00",
                workout_type="cycle",
                distance_km=35.0,
                duration_minutes=90,
                avg_speed_kmh=23.3,
            ),
            _workout(
                self.NO_HR_ID,
                user_id="user-a",
                date="2024-01-09T07:00:00+00:00",
                distance_km=7.0,
                duration_minutes=40,
                avg_pace_min_km=5.8,
            ),
            _workout(
                self.NO_BASELINE_ID,
                user_id="user-a",
                date="2024-01-15T07:00:00+00:00",
                workout_type="swim",
                distance_km=2.0,
                duration_minutes=45,
            ),
            _workout(
                self.ISOLATED_ID,
                user_id="user-a",
                date="2024-02-10T07:00:00+00:00",
                distance_km=9.0,
                duration_minutes=50,
                avg_pace_min_km=5.55,
            ),
            _workout(
                self.OTHER_USER_ID,
                user_id="user-b",
                date="2024-02-05T07:00:00+00:00",
                distance_km=30.0,
                duration_minutes=170,
                avg_heart_rate=171,
                avg_pace_min_km=5.1,
            ),
        ])
        self.user_goals = _Collection()
        self.subscriptions = _Collection()
        self.users = _Collection([
            {"id": "user-a", "email": "a@test.com", "is_active": True, "is_email_verified": True},
            {"id": "user-b", "email": "b@test.com", "is_active": True, "is_email_verified": True},
        ])

    def __getattr__(self, name: str) -> _Collection:
        collection = _Collection()
        object.__setattr__(self, name, collection)
        return collection


def _get_user_access(_db, user_id: str) -> UserAccess:
    if user_id in {"user-a", "user-b"}:
        return UserAccess(user_id=user_id, tier=Tier.PREMIUM)
    return UserAccess(user_id=user_id, tier=Tier.FREE)


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB()
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_get_user_access)),
    ]
    started = []
    try:
        for patcher in patches:
            patcher.start()
            started.append(patcher)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as test_client:
            yield test_client
    finally:
        for patcher in reversed(started):
            patcher.stop()


async def _get_analysis(client, workout_id: str, user_id: str = "user-a"):
    email = "a@test.com" if user_id == "user-a" else "b@test.com"
    return await client.get(
        f"/api/coach/workout-analysis/{workout_id}?language=en",
        headers=_bearer(user_id, email),
    )


async def test_canonical_endpoint_returns_v2_payload(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "v2"
    assert payload["workout"]["id"] == _FakeDB.CURRENT_ID


async def test_idor_returns_404_for_other_users_workout(client):
    response = await _get_analysis(client, _FakeDB.OTHER_USER_ID)
    assert response.status_code == 404


async def test_baseline_is_user_scoped_without_cross_user_contamination(client):
    response = await _get_analysis(client, _FakeDB.ISOLATED_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["available"] is False
    assert payload["comparison"]["baseline_sample_count"] == 0


async def test_identical_input_is_deterministic(client):
    first = await _get_analysis(client, _FakeDB.CURRENT_ID)
    second = await _get_analysis(client, _FakeDB.CURRENT_ID)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


async def test_no_hr_marks_physiology_unavailable(client):
    response = await _get_analysis(client, _FakeDB.NO_HR_ID)
    payload = response.json()
    assert payload["physiology"]["available"] is False
    assert payload["physiology"]["avg_hr"] is None
    assert payload["evidence"]["has_heart_rate"] is False
    assert payload["meaning"]["code"].startswith("meaning.no_hr")


async def test_with_hr_preserves_hr_fields_and_zone_availability(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["physiology"]["available"] is True
    assert payload["physiology"]["avg_hr"] == 150
    assert payload["physiology"]["max_hr"] == 170
    assert payload["physiology"]["zone_distribution"]["z2"] == 50.0
    assert payload["evidence"]["has_hr_zones"] is True


async def test_no_splits_keeps_split_claims_unavailable(client):
    response = await _get_analysis(client, _FakeDB.NO_HR_ID)
    payload = response.json()
    assert payload["evidence"]["has_splits"] is False
    assert payload["pacing"]["fastest_split_min_km"] is None
    assert payload["pacing"]["slowest_split_min_km"] is None


async def test_split_evidence_is_preserved_when_available(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["evidence"]["has_splits"] is True
    assert payload["pacing"]["fastest_split_min_km"] == 5.9
    assert payload["pacing"]["slowest_split_min_km"] == 6.1
    assert payload["pacing"]["consistency_score"] == 92.0


async def test_no_baseline_marks_comparison_unavailable(client):
    response = await _get_analysis(client, _FakeDB.NO_BASELINE_ID)
    payload = response.json()
    assert payload["comparison"]["available"] is False
    assert payload["comparison"]["baseline_sample_count"] == 0
    assert payload["comparison"]["distance_km"] is None


async def test_baseline_uses_same_type_prior_only_and_excludes_current_and_future(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    comparison = payload["comparison"]
    assert comparison["available"] is True
    assert comparison["baseline_sample_count"] == 3
    assert comparison["distance_km"]["baseline"] == 9.0
    assert comparison["duration_minutes"]["baseline"] == 53.33
    assert comparison["avg_heart_rate"]["baseline"] == 146.5


async def test_future_workout_does_not_change_older_workout_analysis(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["comparison"]["baseline_sample_count"] == 3
    assert payload["comparison"]["distance_km"]["baseline"] == 9.0


def test_canonical_service_source_has_no_llm_or_legacy_authority_calls():
    source = Path(workout_analysis_v2.__file__).read_text(encoding="utf-8")
    assert "generate_workout_analysis_rag" not in source
    assert "coach_analyze_workout" not in source
    assert "localize_fields" not in source
    assert "llm" not in source.lower()


def test_canonical_service_source_has_no_random():
    source = Path(workout_analysis_v2.__file__).read_text(encoding="utf-8")
    assert "import random" not in source
    assert "random." not in source


async def test_legacy_routes_return_404_for_authenticated_premium_requests(client):
    headers = _bearer("user-a", "a@test.com")
    detailed = await client.get(f"/api/coach/detailed-analysis/{_FakeDB.CURRENT_ID}?language=en", headers=headers)
    rag = await client.get(f"/api/rag/workout/{_FakeDB.CURRENT_ID}?language=en", headers=headers)
    assert detailed.status_code == 404
    assert rag.status_code == 404


async def test_response_contract_has_required_structured_fields(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert set(payload.keys()) == {
        "version",
        "workout",
        "summary",
        "signals",
        "physiology",
        "pacing",
        "comparison",
        "meaning",
        "advice",
        "evidence",
    }
    assert payload["summary"]["text"]
    assert isinstance(payload["evidence"]["has_baseline"], bool)
    assert payload["comparison"]["baseline_period_days"] == 14
