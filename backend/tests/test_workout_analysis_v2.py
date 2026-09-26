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

    def skip(self, n: int) -> "_Cursor":
        self._docs = self._docs[n:]
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
    avg_cadence_spm: int | None = None,
    cadence_analysis: dict | None = None,
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
        "avg_cadence_spm": avg_cadence_spm,
        "cadence_analysis": cadence_analysis or {},
        "data_source": "garmin",
    }


class _FakeDB:
    CURRENT_ID = "run-current"
    NO_HR_ID = "run-no-hr"
    HR_NO_ZONES_ID = "run-hr-no-zones"
    HIGH_ZONES_ID = "run-high-zones"
    EASY_ZONES_ID = "run-easy-zones"
    NO_BASELINE_ID = "swim-no-baseline"
    ISOLATED_ID = "run-isolated"
    OTHER_USER_ID = "user-b-run"
    MIXED_DATE_ID = "run-mixed-current"
    OLD_TARGET_ID = "run-old-target"
    PACE_SPREAD_ONLY_ID = "run-pace-spread-only"
    CADENCE_ID = "run-cadence"

    def __init__(self) -> None:
        workouts = [
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
                self.NO_HR_ID,
                user_id="user-a",
                date="2024-01-09T07:00:00+00:00",
                distance_km=7.0,
                duration_minutes=40,
                avg_pace_min_km=5.8,
            ),
            _workout(
                self.HR_NO_ZONES_ID,
                user_id="user-a",
                date="2024-01-08T07:00:00+00:00",
                distance_km=6.0,
                duration_minutes=35,
                avg_heart_rate=170,
                max_heart_rate=180,
                avg_pace_min_km=5.85,
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
                self.HIGH_ZONES_ID,
                user_id="user-a",
                date="2024-03-10T07:00:00+00:00",
                distance_km=9.0,
                duration_minutes=50,
                avg_heart_rate=166,
                max_heart_rate=184,
                effort_zone_distribution={"z1": 5, "z2": 25, "z3": 20, "z4": 30, "z5": 20},
            ),
            _workout(
                self.EASY_ZONES_ID,
                user_id="user-a",
                date="2024-03-11T07:00:00+00:00",
                distance_km=8.0,
                duration_minutes=46,
                avg_heart_rate=128,
                max_heart_rate=145,
                effort_zone_distribution={"z1": 35, "z2": 40, "z3": 20, "z4": 5, "z5": 0},
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
            _workout(
                self.MIXED_DATE_ID,
                user_id="user-a",
                date="2026-09-10",
                distance_km=10.0,
                duration_minutes=60,
                avg_pace_min_km=6.0,
            ),
            _workout(
                "run-mixed-prev-z",
                user_id="user-a",
                date="2026-09-05T07:00:00Z",
                distance_km=8.0,
                duration_minutes=48,
                avg_pace_min_km=6.0,
            ),
            _workout(
                "run-mixed-prev-offset",
                user_id="user-a",
                date="2026-09-06T08:00:00+02:00",
                distance_km=9.0,
                duration_minutes=52,
                avg_pace_min_km=5.95,
            ),
            _workout(
                "run-mixed-future",
                user_id="user-a",
                date="2026-09-12",
                distance_km=14.0,
                duration_minutes=82,
                avg_pace_min_km=5.8,
            ),
            _workout(
                self.OLD_TARGET_ID,
                user_id="user-a",
                date="2023-01-01T07:00:00+00:00",
                distance_km=11.0,
                duration_minutes=66,
                avg_heart_rate=151,
                max_heart_rate=172,
                effort_zone_distribution={"z1": 15, "z2": 45, "z3": 25, "z4": 15, "z5": 0},
            ),
            _workout(
                self.PACE_SPREAD_ONLY_ID,
                user_id="user-a",
                date="2024-03-12T07:00:00+00:00",
                distance_km=10.0,
                duration_minutes=60,
                avg_pace_min_km=6.0,
                km_splits=[
                    {"km": 1, "pace_min_km": 5.7, "pace_str": "5:42"},
                    {"km": 2, "pace_min_km": 6.4, "pace_str": "6:24"},
                ],
                split_analysis={
                    "fastest_split_pace": 5.7,
                    "slowest_split_pace": 6.4,
                },
            ),
            _workout(
                self.CADENCE_ID,
                user_id="user-a",
                date="2024-03-13T07:00:00+00:00",
                distance_km=7.5,
                duration_minutes=42,
                avg_pace_min_km=5.6,
                avg_cadence_spm=176,
            ),
        ]

        for idx in range(250):
            workouts.append(
                _workout(
                    f"run-newer-{idx}",
                    user_id="user-a",
                    date=f"2023-02-{(idx % 28) + 1:02d}T07:00:00+00:00",
                    distance_km=5.0,
                    duration_minutes=30,
                )
            )

        self.workouts = _Collection(workouts)
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


@pytest.mark.asyncio
async def test_canonical_endpoint_returns_v2_payload(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "v2"
    assert payload["workout"]["id"] == _FakeDB.CURRENT_ID


@pytest.mark.asyncio
async def test_idor_returns_404_for_other_users_workout(client):
    response = await _get_analysis(client, _FakeDB.OTHER_USER_ID)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_baseline_is_user_scoped_without_cross_user_contamination(client):
    response = await _get_analysis(client, _FakeDB.ISOLATED_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["available"] is False
    assert payload["comparison"]["baseline_sample_count"] == 0


@pytest.mark.asyncio
async def test_identical_input_is_deterministic(client):
    first = await _get_analysis(client, _FakeDB.CURRENT_ID)
    second = await _get_analysis(client, _FakeDB.CURRENT_ID)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


@pytest.mark.asyncio
async def test_no_hr_marks_physiology_and_intensity_unavailable(client):
    response = await _get_analysis(client, _FakeDB.NO_HR_ID)
    payload = response.json()
    assert payload["physiology"]["available"] is False
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["intensity"]["code"] is None
    assert payload["signals"]["intensity"]["text"] is None
    assert payload["meaning"]["code"].startswith("meaning.no_hr")


@pytest.mark.asyncio
async def test_hr_without_zones_preserves_raw_hr_but_not_intensity_classification(client):
    response = await _get_analysis(client, _FakeDB.HR_NO_ZONES_ID)
    payload = response.json()
    assert payload["physiology"]["available"] is True
    assert payload["physiology"]["avg_hr"] == 170
    assert payload["physiology"]["max_hr"] == 180
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["intensity"]["code"] is None
    assert payload["advice"]["code"] == "advice.hr_without_intensity"


@pytest.mark.asyncio
async def test_hr_zones_high_enable_high_intensity_classification(client):
    response = await _get_analysis(client, _FakeDB.HIGH_ZONES_ID)
    payload = response.json()
    assert payload["signals"]["intensity"]["available"] is True
    assert payload["signals"]["intensity"]["code"] == "very_high"


@pytest.mark.asyncio
async def test_hr_zones_easy_enable_low_intensity_classification(client):
    response = await _get_analysis(client, _FakeDB.EASY_ZONES_ID)
    payload = response.json()
    assert payload["signals"]["intensity"]["available"] is True
    assert payload["signals"]["intensity"]["code"] == "low"


@pytest.mark.asyncio
async def test_no_splits_keeps_split_claims_unavailable(client):
    response = await _get_analysis(client, _FakeDB.NO_HR_ID)
    payload = response.json()
    assert payload["evidence"]["has_splits"] is False
    assert payload["pacing"]["fastest_split_min_km"] is None
    assert payload["pacing"]["slowest_split_min_km"] is None


@pytest.mark.asyncio
async def test_split_evidence_and_true_pace_drop_are_preserved(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["evidence"]["has_splits"] is True
    assert payload["pacing"]["fastest_split_min_km"] == 5.9
    assert payload["pacing"]["slowest_split_min_km"] == 6.1
    assert payload["pacing"]["pace_drop_min_km"] == 0.2
    assert payload["pacing"]["consistency_score"] == 92.0


@pytest.mark.asyncio
async def test_fastest_slowest_spread_does_not_create_fake_pace_drop(client):
    response = await _get_analysis(client, _FakeDB.PACE_SPREAD_ONLY_ID)
    payload = response.json()
    assert payload["pacing"]["fastest_split_min_km"] == 5.7
    assert payload["pacing"]["slowest_split_min_km"] == 6.4
    assert payload["pacing"]["pace_drop_min_km"] is None


@pytest.mark.asyncio
async def test_no_baseline_uses_structural_volume_language(client):
    response = await _get_analysis(client, _FakeDB.NO_BASELINE_ID)
    payload = response.json()
    assert payload["comparison"]["available"] is False
    assert payload["comparison"]["baseline_sample_count"] == 0
    assert payload["signals"]["volume"]["code"] in {"short_volume", "medium_volume", "long_volume"}
    assert "recent" not in (payload["signals"]["volume"]["text"] or "").lower()
    assert "usual" not in (payload["signals"]["volume"]["text"] or "").lower()


@pytest.mark.asyncio
async def test_baseline_present_allows_relative_volume_language(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["comparison"]["available"] is True
    assert payload["comparison"]["baseline_sample_count"] == 4
    assert payload["signals"]["volume"]["code"] in {"below_recent", "usual_recent", "above_recent"}


@pytest.mark.asyncio
async def test_mixed_date_formats_are_normalized_without_lookahead_crashes(client):
    response = await _get_analysis(client, _FakeDB.MIXED_DATE_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["comparison"]["available"] is True
    assert payload["comparison"]["baseline_sample_count"] == 2


@pytest.mark.asyncio
async def test_old_owned_target_beyond_latest_200_is_found_directly(client):
    response = await _get_analysis(client, _FakeDB.OLD_TARGET_ID)
    assert response.status_code == 200
    payload = response.json()
    assert payload["workout"]["id"] == _FakeDB.OLD_TARGET_ID


@pytest.mark.asyncio
async def test_future_workout_does_not_change_older_workout_analysis(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["comparison"]["baseline_sample_count"] == 4


@pytest.mark.asyncio
async def test_cadence_evidence_is_preserved(client):
    response = await _get_analysis(client, _FakeDB.CADENCE_ID)
    payload = response.json()
    assert payload["evidence"]["has_cadence"] is True


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


@pytest.mark.asyncio
async def test_legacy_routes_return_404_for_authenticated_premium_requests(client):
    headers = _bearer("user-a", "a@test.com")
    detailed = await client.get(f"/api/coach/detailed-analysis/{_FakeDB.CURRENT_ID}?language=en", headers=headers)
    rag = await client.get(f"/api/rag/workout/{_FakeDB.CURRENT_ID}?language=en", headers=headers)
    assert detailed.status_code == 404
    assert rag.status_code == 404


@pytest.mark.asyncio
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
    assert payload["signals"]["intensity"]["available"] is True
    assert payload["summary"]["text"]
    assert isinstance(payload["evidence"]["has_baseline"], bool)
    assert payload["comparison"]["baseline_period_days"] == 14
