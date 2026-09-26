from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET_KEY", "rag-endpoints-test-secret-32chars!!")
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

    async def find_one(self, query: dict, projection: dict | None = None, sort=None) -> dict | None:
        docs = [dict(doc) for doc in self._docs if self._matches(doc, query)]
        if sort:
            for key, direction in reversed(sort):
                docs.sort(key=lambda doc: doc.get(key, ""), reverse=direction == -1)
        if not docs:
            return None
        result = docs[0]
        if projection:
            result = {k: v for k, v in result.items() if projection.get(k, 1)}
        return result

    async def insert_one(self, doc: dict):
        self._docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("id"))

    async def count_documents(self, query: dict) -> int:
        return sum(1 for doc in self._docs if self._matches(doc, query))

    async def create_index(self, *args, **kwargs) -> None:
        return None


class _FakeDB:
    def __init__(self) -> None:
        self.workouts = _Collection([
            {
                "id": "run-1",
                "user_id": "user-a",
                "type": "run",
                "name": "Run 1",
                "date": "2024-01-10T07:00:00+00:00",
                "distance_km": 10.0,
                "duration_minutes": 60,
            },
            {
                "id": "run-2",
                "user_id": "user-a",
                "type": "run",
                "name": "Run 2",
                "date": "2024-01-08T07:00:00+00:00",
                "distance_km": 8.0,
                "duration_minutes": 48,
            },
            {
                "id": "other-user-run",
                "user_id": "user-b",
                "type": "run",
                "name": "Other User Run",
                "date": "2024-01-09T07:00:00+00:00",
                "distance_km": 30.0,
                "duration_minutes": 170,
            },
        ])
        self.digests = _Collection([
            {
                "id": "digest-1",
                "user_id": "user-a",
                "generated_at": "2024-01-10T08:00:00+00:00",
                "coach_summary": "Digest",
            }
        ])
        self.user_goals = _Collection([{"user_id": "user-a", "goal": "marathon"}])
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
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


@pytest_asyncio.fixture
async def client():
    fake_db = _FakeDB()
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_get_user_access)),
        patch.object(server, "_dic", SimpleNamespace(get=lambda *args, **kwargs: None, set=lambda *args, **kwargs: None)),
        patch("server.generate_dashboard_rag", return_value={
            "summary": "Dashboard summary",
            "metrics": {"km_total": 18.0, "nb_seances": 2, "allure_moy": "6:00/km", "duree_totale": "1h48"},
            "points_forts": ["consistent"],
            "points_ameliorer": ["speed"],
            "tips": ["keep going"],
        }),
        patch("server.generate_weekly_review_rag", return_value={
            "metrics": {"km_total": 18.0},
            "comparison": {"vs_prev_week": "+10%", "km_current": 18.0},
            "points_forts": ["consistent"],
            "points_ameliorer": ["speed"],
            "tips": ["recover"],
        }),
        patch("server.coach_weekly_review", AsyncMock(return_value=("Weekly review summary", False))),
        patch("server.load_garmin_domain_activities", AsyncMock(return_value=[SimpleNamespace(id="ga-1")])),
        patch("server.calculate_week_stats_from_domain", return_value={"sessions": 2, "volume_km": 18.0}),
        patch("server.calculate_month_stats_from_domain", return_value={"sessions": 6, "volume_km": 60.0}),
        patch("server.calculate_run_index_from_domain", return_value={"score": 52.1}),
        patch("server.upsert_run_index_snapshot", AsyncMock(return_value=None)),
        patch("server.generate_dashboard_insight", return_value="Coach insight"),
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


@pytest.mark.asyncio
async def test_rag_dashboard_coverage_is_preserved(client):
    response = await client.get("/api/rag/dashboard", headers=_bearer("user-a", "a@test.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["rag_summary"] == "Dashboard summary"
    assert payload["metrics"]["km_total"] == 18.0
    assert payload["metrics"]["nb_seances"] == 2
    assert payload["points_forts"] == ["consistent"]


@pytest.mark.asyncio
async def test_rag_weekly_review_coverage_is_preserved(client):
    response = await client.get("/api/rag/weekly-review?language=en", headers=_bearer("user-a", "a@test.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["rag_summary"] == "Weekly review summary"
    assert payload["comparison"]["km_current"] == 18.0
    assert payload["enriched_by_llm"] is False


@pytest.mark.asyncio
async def test_workouts_endpoint_coverage_is_preserved(client):
    response = await client.get("/api/workouts", headers=_bearer("user-a", "a@test.com"))
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert {item["id"] for item in payload} == {"run-1", "run-2"}
    assert {"id", "type", "name", "date", "distance_km"} <= set(payload[0].keys())


@pytest.mark.asyncio
async def test_dashboard_insight_coverage_is_preserved(client):
    response = await client.get("/api/dashboard/insight?language=en", headers=_bearer("user-a", "a@test.com"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["coach_insight"] == "Coach insight"
    assert payload["week"]["sessions"] == 2
    assert payload["month"]["volume_km"] == 60.0
    assert payload["run_index"]["score"] == 52.1
