from __future__ import annotations

import inspect
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
    def __init__(self, docs: list[dict], collection=None) -> None:
        self._docs = list(docs)
        self._collection = collection

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
        if self._collection is not None:
            self._collection.to_list_lengths.append(length)
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs: list[dict] | None = None) -> None:
        self._docs = list(docs or [])
        self.find_queries: list[dict] = []
        self.to_list_lengths: list[int | None] = []

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                for operator, operator_value in expected.items():
                    if operator == "$gte":
                        if actual is None or actual < operator_value:
                            return False
                    elif operator == "$lt":
                        if actual is None or actual >= operator_value:
                            return False
                    else:
                        raise AssertionError(f"Unsupported operator {operator}")
            elif actual != expected:
                return False
        return True

    def find(self, query: dict | None = None, projection: dict | None = None) -> _Cursor:
        q = query or {}
        self.find_queries.append(dict(q))
        docs = [dict(doc) for doc in self._docs if self._matches(doc, q)]
        if projection:
            docs = [{k: v for k, v in doc.items() if projection.get(k, 1)} for doc in docs]
        return _Cursor(docs, collection=self)

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
    elevation_gain_m: int | None = None,
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
        "elevation_gain_m": elevation_gain_m,
        "data_source": "garmin",
    }


class _FakeDB:
    CURRENT_ID = "run-current"
    NO_HR_ID = "run-no-hr"
    HR_NO_ZONES_ID = "run-hr-no-zones"
    HIGH_ZONES_ID = "run-high-zones"
    EASY_ZONES_ID = "run-easy-zones"
    SHORT_STRUCTURAL_ID = "run-short-structural"
    LONG_STRUCTURAL_ID = "run-long-structural"
    RUN_DISTANCE_LONG_ID = "run-distance-long"
    CYCLE_STANDARD_ID = "cycle-standard"
    CYCLE_LONG_ID = "cycle-long"
    SWIM_STANDARD_ID = "swim-standard"
    SWIM_SHORT_ID = "swim-short"
    UNKNOWN_STANDARD_ID = "row-standard"
    NO_BASELINE_ID = "swim-no-baseline"
    ISOLATED_ID = "run-isolated"
    OTHER_USER_ID = "user-b-run"
    MIXED_DATE_ID = "run-mixed-current"
    OLD_TARGET_ID = "run-old-target"
    PACE_SPREAD_ONLY_ID = "run-pace-spread-only"
    CADENCE_ID = "run-cadence"
    FIXTURE_A_ID = "run-fixture-a"
    FIXTURE_B_ID = "run-fixture-b"
    NO_REFERENCE_ID = "run-fixture-no-reference"

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
                self.SHORT_STRUCTURAL_ID,
                user_id="user-a",
                date="2024-03-14T07:00:00+00:00",
                distance_km=3.5,
                duration_minutes=22,
                avg_pace_min_km=6.2,
            ),
            _workout(
                self.LONG_STRUCTURAL_ID,
                user_id="user-a",
                date="2024-03-15T07:00:00+00:00",
                distance_km=18.0,
                duration_minutes=105,
                avg_pace_min_km=5.9,
                avg_heart_rate=155,
            ),
            _workout(
                self.RUN_DISTANCE_LONG_ID,
                user_id="user-a",
                date="2024-04-16T07:00:00+00:00",
                distance_km=16.0,
                duration_minutes=70,
                avg_pace_min_km=4.38,
            ),
            _workout(
                self.CYCLE_STANDARD_ID,
                user_id="user-a",
                date="2024-04-17T07:00:00+00:00",
                workout_type="cycle",
                distance_km=20.0,
                duration_minutes=40,
                avg_speed_kmh=30.0,
            ),
            _workout(
                self.CYCLE_LONG_ID,
                user_id="user-a",
                date="2024-05-18T07:00:00+00:00",
                workout_type="cycle",
                distance_km=35.0,
                duration_minutes=100,
                avg_speed_kmh=21.0,
            ),
            _workout(
                self.SWIM_STANDARD_ID,
                user_id="user-a",
                date="2024-04-19T07:00:00+00:00",
                workout_type="swim",
                distance_km=2.0,
                duration_minutes=45,
            ),
            _workout(
                self.SWIM_SHORT_ID,
                user_id="user-a",
                date="2024-05-20T07:00:00+00:00",
                workout_type="swim",
                distance_km=1.5,
                duration_minutes=20,
            ),
            _workout(
                self.UNKNOWN_STANDARD_ID,
                user_id="user-a",
                date="2024-04-21T07:00:00+00:00",
                workout_type="row",
                distance_km=20.0,
                duration_minutes=40,
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
                "run-old-outside-window",
                user_id="user-a",
                date="2026-08-01T07:00:00+00:00",
                distance_km=30.0,
                duration_minutes=180,
                avg_pace_min_km=6.0,
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
            # ---- PR303 representative fixtures -------------------------------
            # Session A: half-marathon distance run, splits available,
            # no validated heart-rate zone provenance.
            _workout(
                self.FIXTURE_A_ID,
                user_id="user-a",
                date="2025-06-15T07:00:00+00:00",
                distance_km=21.27,
                duration_minutes=122,
                avg_heart_rate=160,
                max_heart_rate=174,
                avg_pace_min_km=5.7167,
                km_splits=[
                    {"km": index + 1, "pace_min_km": pace}
                    for index, pace in enumerate([5.4, 5.5, 5.6, 5.6, 5.7, 5.7, 5.8, 5.8, 5.9, 6.0])
                ],
                split_analysis={
                    "fastest_split_pace": 5.4,
                    "slowest_split_pace": 6.0,
                    "pace_drop": 0.6,
                    "negative_split": False,
                    "consistency_score": 88,
                },
                hr_analysis={"hr_drift": 9},
                avg_cadence_spm=172,
                elevation_gain_m=210,
            ),
            _workout(
                "run-fixture-a-prev-1",
                user_id="user-a",
                date="2025-06-01T07:00:00+00:00",
                distance_km=20.5,
                duration_minutes=120,
                avg_heart_rate=158,
                avg_pace_min_km=5.85,
            ),
            _workout(
                "run-fixture-a-prev-2",
                user_id="user-a",
                date="2025-05-18T07:00:00+00:00",
                distance_km=22.0,
                duration_minutes=131,
                avg_heart_rate=162,
                avg_pace_min_km=5.95,
            ),
            _workout(
                "run-fixture-a-future",
                user_id="user-a",
                date="2025-06-20T07:00:00+00:00",
                distance_km=21.0,
                duration_minutes=115,
                avg_heart_rate=159,
                avg_pace_min_km=5.48,
            ),
            _workout(
                "run-fixture-a-too-short",
                user_id="user-a",
                date="2025-06-05T07:00:00+00:00",
                distance_km=8.0,
                duration_minutes=47,
                avg_pace_min_km=5.9,
            ),
            # Session B: easy-distance run, no splits, no validated zone provenance,
            # and a single comparable earlier session (insufficient sample).
            _workout(
                self.FIXTURE_B_ID,
                user_id="user-a",
                date="2025-12-10T07:00:00+00:00",
                distance_km=10.18,
                duration_minutes=71,
                avg_heart_rate=127,
                avg_pace_min_km=6.9833,
            ),
            _workout(
                "run-fixture-b-prev-1",
                user_id="user-a",
                date="2025-12-01T07:00:00+00:00",
                distance_km=10.0,
                duration_minutes=70,
                avg_heart_rate=130,
                avg_pace_min_km=7.05,
            ),
            # Session with pacing facts but no comparable earlier distance at all.
            _workout(
                self.NO_REFERENCE_ID,
                user_id="user-a",
                date="2025-11-20T07:00:00+00:00",
                distance_km=32.0,
                duration_minutes=205,
                avg_pace_min_km=6.4,
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
        patch.object(server.app.state, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_get_user_access)),
        patch.object(server, "rate_limiter", server.RateLimiter(requests_per_minute=1000, burst_limit=1000)),
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
            test_client.fake_db = fake_db  # type: ignore[attr-defined]
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
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert "steady" not in payload["signals"]["session_type"]["text"].lower()
    assert "consistent" not in payload["summary"]["text"].lower()
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
async def test_zone_distribution_presence_does_not_unlock_intensity_without_trusted_provenance(client):
    response = await _get_analysis(client, _FakeDB.HIGH_ZONES_ID)
    payload = response.json()
    assert payload["evidence"]["has_hr_zones"] is True
    assert payload["physiology"]["zone_distribution"]["z5"] == 20.0
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["intensity"]["code"] is None
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert "hard" not in payload["summary"]["text"].lower()


@pytest.mark.asyncio
async def test_easy_looking_zone_distribution_still_remains_non_authoritative_without_provenance(client):
    response = await _get_analysis(client, _FakeDB.EASY_ZONES_ID)
    payload = response.json()
    assert payload["evidence"]["has_hr_zones"] is True
    assert payload["physiology"]["zone_distribution"]["z1"] == 35.0
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert "easy" not in payload["summary"]["text"].lower()


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
async def test_structural_standard_session_uses_neutral_structural_wording(client):
    response = await _get_analysis(client, _FakeDB.HR_NO_ZONES_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert payload["signals"]["session_type"]["text"] == "Standard session"
    lowered_summary = payload["summary"]["text"].lower()
    assert lowered_summary.startswith("you covered 6 km in 35 min at 5:51/km.")
    assert "your average heart rate was 170 bpm (peak 180 bpm)." in lowered_summary
    for forbidden in ("steady", "consistent", "regular"):
        assert forbidden not in lowered_summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "distance_fact", "heart_rate_fact", "forbidden"),
    [
        ("fr", "Tu as parcouru 6 km en 35 min à 5:51/km.", "Ta fréquence cardiaque moyenne était de 170 bpm (max 180 bpm).", ("facile", "modérée", "intense", "endurance fondamentale")),
        ("en", "You covered 6 km in 35 min at 5:51/km.", "Your average heart rate was 170 bpm (peak 180 bpm).", ("easy", "moderate", "intense", "fundamental endurance")),
        ("es", "Recorriste 6 km en 35 min a 5:51/km.", "Tu frecuencia cardíaca media fue de 170 bpm (máxima 180 bpm).", ("fácil", "moderada", "intensa", "easy")),
    ],
)
async def test_unavailable_intensity_summary_leads_with_natural_facts_in_all_languages(
    client, language, distance_fact, heart_rate_fact, forbidden
):
    payload = (await _get_analysis_lang(client, _FakeDB.HR_NO_ZONES_ID, language)).json()
    summary = payload["summary"]["text"]

    assert payload["signals"]["intensity"]["available"] is False
    assert distance_fact in summary
    assert heart_rate_fact in summary
    assert "Standard-duration session completed" not in summary
    assert "Séance de durée standard réalisée" not in summary
    assert "Sesión de duración estándar completada" not in summary
    assert all(term not in summary.lower() for term in forbidden)
    assert payload["physiology"]["avg_hr"] == 170
    assert payload["physiology"]["max_hr"] == 180
    assert payload["pacing"]["average_pace_min_km"] == 5.85


@pytest.mark.asyncio
async def test_short_structural_session_is_allowed_without_intensity_evidence(client):
    response = await _get_analysis(client, _FakeDB.SHORT_STRUCTURAL_ID)
    payload = response.json()
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["session_type"]["code"] == "short"


@pytest.mark.asyncio
async def test_long_structural_session_is_allowed_without_intensity_evidence(client):
    response = await _get_analysis(client, _FakeDB.LONG_STRUCTURAL_ID)
    payload = response.json()
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["signals"]["session_type"]["code"] == "long"


@pytest.mark.asyncio
async def test_running_distance_threshold_can_make_structural_session_long(client):
    response = await _get_analysis(client, _FakeDB.RUN_DISTANCE_LONG_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "long"
    assert payload["signals"]["volume"]["code"] == "long_volume"
    assert payload["summary"]["code"] == "summary.long_structural"


@pytest.mark.asyncio
async def test_cycle_distance_does_not_trigger_running_long_thresholds(client):
    response = await _get_analysis(client, _FakeDB.CYCLE_STANDARD_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert payload["signals"]["volume"]["code"] == "medium_volume"
    assert payload["summary"]["code"] == "summary.standard_structural"
    assert "long" not in payload["summary"]["text"].lower()


@pytest.mark.asyncio
async def test_swim_distance_does_not_trigger_running_short_thresholds(client):
    response = await _get_analysis(client, _FakeDB.SWIM_STANDARD_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert payload["signals"]["volume"]["code"] == "medium_volume"
    assert payload["summary"]["code"] == "summary.standard_structural"
    assert "short" not in payload["summary"]["text"].lower()


@pytest.mark.asyncio
async def test_cycle_long_by_duration_is_allowed(client):
    response = await _get_analysis(client, _FakeDB.CYCLE_LONG_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "long"
    assert payload["signals"]["volume"]["code"] == "long_volume"


@pytest.mark.asyncio
async def test_swim_short_by_duration_is_allowed(client):
    response = await _get_analysis(client, _FakeDB.SWIM_SHORT_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "short"
    assert payload["signals"]["volume"]["code"] == "short_volume"


@pytest.mark.asyncio
async def test_unknown_type_uses_duration_only_structural_logic(client):
    response = await _get_analysis(client, _FakeDB.UNKNOWN_STANDARD_ID)
    payload = response.json()
    assert payload["signals"]["session_type"]["code"] == "standard"
    assert payload["signals"]["volume"]["code"] == "medium_volume"


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
async def test_history_query_is_bounded_to_candidate_date_window(client):
    client.fake_db.workouts.find_queries.clear()
    client.fake_db.workouts.to_list_lengths.clear()
    response = await _get_analysis(client, _FakeDB.MIXED_DATE_ID)
    assert response.status_code == 200
    history_query = client.fake_db.workouts.find_queries[-1]
    assert history_query["user_id"] == "user-a"
    assert history_query["type"] == "run"
    # The window covers the bounded similar-workout search (180 days) and still
    # excludes anything at or after the current workout date.
    assert history_query["date"] == {"$gte": "2026-03-14", "$lt": "2026-09-11"}
    assert client.fake_db.workouts.to_list_lengths[-1] == 200


@pytest.mark.asyncio
async def test_endpoint_candidate_query_stays_bounded_and_excludes_future_activities(client):
    client.fake_db.workouts.find_queries.clear()
    response = await _get_analysis(client, _FakeDB.MIXED_DATE_ID)
    assert response.status_code == 200
    candidate_docs = [
        doc for doc in client.fake_db.workouts._docs
        if client.fake_db.workouts._matches(doc, client.fake_db.workouts.find_queries[-1])
    ]
    candidate_ids = {doc["id"] for doc in candidate_docs}
    assert {"run-mixed-prev-z", "run-mixed-prev-offset"} <= candidate_ids
    assert "run-mixed-future" not in candidate_ids
    # Anything older than the bounded history window stays out of the query.
    assert "run-newer-0" not in candidate_ids
    assert "user-b-run" not in candidate_ids


@pytest.mark.asyncio
async def test_future_workout_does_not_change_older_workout_analysis(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["comparison"]["baseline_sample_count"] == 4


@pytest.mark.asyncio
async def test_api_ignores_malformed_zone_values_without_crashing(client):
    malformed = _workout(
        "run-malformed-zones",
        user_id="user-a",
        date="2024-03-22T07:00:00+00:00",
        distance_km=10.0,
        duration_minutes=60,
        avg_heart_rate=150,
        effort_zone_distribution={"z1": "abc", "z2": None, "z3": [], "z4": {}, "zone6": 50},
    )
    await client.fake_db.workouts.insert_one(malformed)
    response = await _get_analysis(client, "run-malformed-zones")
    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence"]["has_hr_zones"] is False
    assert payload["physiology"]["zone_distribution"] is None
    assert payload["signals"]["intensity"]["available"] is False


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
        "limitations",
    }
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["summary"]["text"]
    assert isinstance(payload["evidence"]["has_baseline"], bool)
    assert payload["comparison"]["baseline_period_days"] == 14


# ============================================================
# PR303 — restored factual, session-specific analysis
# ============================================================


async def _get_analysis_lang(client, workout_id: str, language: str, user_id: str = "user-a"):
    email = "a@test.com" if user_id == "user-a" else "b@test.com"
    return await client.get(
        f"/api/coach/workout-analysis/{workout_id}?language={language}",
        headers=_bearer(user_id, email),
    )


# Workout Analysis V2 describes and compares; Training Today/Week V2 remain the only
# prescription authorities. These phrasings decide what the athlete should do next and
# are therefore forbidden in every supported language.
PRESCRIPTIVE_PHRASES_EN = (
    "next session",
    "easy day",
    "rest day",
    "more conservatively",
    "repeat this distance",
    "repeating this distance",
    "reuse this",
    "keep this control",
    "plan an easy",
    "use individualized",
    "use heart-rate recording",
)
PRESCRIPTIVE_PHRASES_FR = (
    "prochaine séance",
    "journée facile",
    "journée de repos",
    "plus prudemment",
    "répéter cette distance",
    "réutilise",
    "prévois",
    "garde la prochaine",
    "utilise des zones",
    "fais progresser",
)
PRESCRIPTIVE_PHRASES_ES = (
    "próxima sesión",
    "día suave",
    "día de descanso",
    "más conservador",
    "repetir esta distancia",
    "reutiliza",
    "planifica",
    "usa zonas",
    "mantén ese control",
)
PRESCRIPTIVE_PHRASES = (
    PRESCRIPTIVE_PHRASES_EN + PRESCRIPTIVE_PHRASES_FR + PRESCRIPTIVE_PHRASES_ES
)

# Advice codes are observation/limit codes only. Any prescription-shaped code is banned.
ALLOWED_ADVICE_CODES = {
    "advice.high_intensity_observation",
    "advice.low_intensity_observation",
    "advice.even_pacing",
    "advice.negative_split_confirmed",
    "advice.maintain_consistency",
    "advice.monitor_hr_drift",
    "advice.recover_after_long",
    "advice.hr_without_intensity",
    "advice.no_hr",
}


def _assert_not_prescriptive(text: str) -> None:
    lowered = text.lower()
    for phrase in PRESCRIPTIVE_PHRASES:
        assert phrase not in lowered, f"prescriptive phrasing found: {phrase!r} in {text!r}"


@pytest.mark.asyncio
async def test_fixture_a_summary_reports_its_own_distance_duration_pace_and_hr(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    summary = payload["summary"]["text"]
    assert "21.27 km" in summary
    assert "2h02" in summary
    assert "5:43/km" in summary
    assert "160 bpm" in summary
    assert "174 bpm" in summary


@pytest.mark.asyncio
async def test_fixture_a_meaning_selects_one_observation_without_repeating_metrics(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    meaning = payload["meaning"]["text"]
    assert payload["meaning"]["code"] == "meaning.pace_change"
    assert len(meaning) <= 240
    for metric in ("5:24/km", "6:00/km", "10 splits", "0:36/km", "88/100", "9 bpm", "210 m", "172 spm"):
        assert metric not in meaning
    assert payload["pacing"]["consistency_score"] == 88
    assert payload["physiology"]["hr_drift"] == 9
    assert payload["evidence"]["has_elevation"] is True
    assert payload["evidence"]["has_cadence"] is True
    # No automatic causal attribution for the measured drift.
    lowered = meaning.lower()
    assert "fatigue" not in lowered
    assert "dehydr" not in lowered
    # Facts come first: the intensity caveat is only a closing statement.
    assert not lowered.startswith("heart-rate facts are available")


@pytest.mark.asyncio
async def test_fixture_a_advice_is_specific_useful_and_non_prescriptive(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    assert payload["advice"]["code"] == "advice.even_pacing"
    assert "individualized heart-rate zones" not in payload["advice"]["text"]
    text = payload["advice"]["text"]
    # Specific to the observed pacing fact, not a generic fallback.
    assert "pace change" in text
    _assert_not_prescriptive(text)


@pytest.mark.asyncio
async def test_fixture_b_analysis_is_specific_and_differs_from_fixture_a(client):
    payload_a = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    payload_b = (await _get_analysis(client, _FakeDB.FIXTURE_B_ID)).json()
    summary_b = payload_b["summary"]["text"]
    assert "10.18 km" in summary_b
    assert "1h11" in summary_b
    assert "6:59/km" in summary_b
    assert "127 bpm" in summary_b
    assert "174 bpm" not in summary_b
    assert summary_b != payload_a["summary"]["text"]
    assert payload_b["meaning"]["text"] != payload_a["meaning"]["text"]
    assert payload_b["advice"]["text"] != payload_a["advice"]["text"]


@pytest.mark.asyncio
async def test_fixtures_do_not_invent_splits_zones_or_session_nature(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_B_ID)).json()
    assert payload["evidence"]["has_splits"] is False
    assert payload["evidence"]["has_hr_zones"] is False
    assert payload["pacing"]["fastest_split_min_km"] is None
    assert payload["pacing"]["slowest_split_min_km"] is None
    assert payload["pacing"]["negative_split"] is None
    assert payload["physiology"]["zone_distribution"] is None
    meaning = payload["meaning"]["text"].lower()
    assert "splits recorded" not in meaning
    assert "interval" not in meaning
    assert "tempo" not in meaning


@pytest.mark.asyncio
async def test_fixtures_never_infer_intensity_from_average_heart_rate(client):
    for workout_id in (_FakeDB.FIXTURE_A_ID, _FakeDB.FIXTURE_B_ID):
        payload = (await _get_analysis(client, workout_id)).json()
        assert payload["signals"]["intensity"]["available"] is False
        assert payload["signals"]["intensity"]["code"] is None
        assert payload["evidence"]["has_hr_zones"] is False


@pytest.mark.asyncio
async def test_fixture_b_advice_is_unavailable_and_limits_are_separate(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_B_ID)).json()
    assert payload["advice"]["code"] == "advice.hr_without_intensity"
    text = payload["advice"]["text"]
    assert payload["advice"]["available"] is False
    assert text == "No usable coaching observation is available from these data."
    assert "Limit of this analysis" not in text
    assert {"limitations.intensity", "limitations.splits"} <= {
        item["code"] for item in payload["limitations"]
    }
    _assert_not_prescriptive(text)


@pytest.mark.asyncio
async def test_similar_history_uses_comparable_prior_sessions_only(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["available"] is True
    assert similar["sample_count"] == 2
    # P2: an unrecorded training/race nature forbids asserting strong comparability.
    assert similar["comparable"] is False
    assert set(similar["workout_ids"]) == {"run-fixture-a-prev-1", "run-fixture-a-prev-2"}
    assert similar["distance_tolerance_pct"] == 30.0
    assert similar["period_days"] == 180
    assert similar["pace_difference_min_km"] is not None
    assert "session_nature_unknown" in similar["limitations"]


@pytest.mark.asyncio
async def test_similar_history_excludes_future_and_non_comparable_distances(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    similar_ids = set(payload["comparison"]["similar"]["workout_ids"])
    assert "run-fixture-a-future" not in similar_ids
    assert "run-fixture-a-too-short" not in similar_ids
    assert _FakeDB.FIXTURE_A_ID not in similar_ids


@pytest.mark.asyncio
async def test_similar_history_is_user_scoped(client):
    await client.fake_db.workouts.insert_one(
        _workout(
            "run-other-user-comparable",
            user_id="user-b",
            date="2025-06-02T07:00:00+00:00",
            distance_km=21.0,
            duration_minutes=110,
            avg_heart_rate=150,
            avg_pace_min_km=5.2,
        )
    )
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["sample_count"] == 2
    assert "run-other-user-comparable" not in set(similar["workout_ids"])


@pytest.mark.asyncio
async def test_insufficient_similar_sample_is_not_presented_as_progression(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_B_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["available"] is True
    assert similar["comparable"] is False
    assert similar["sample_count"] == 1
    assert "sample_too_small" in similar["limitations"]
    meaning = payload["meaning"]["text"]
    assert "below the 2 this analysis requires" not in meaning
    assert "limitations.sample_too_small" in {item["code"] for item in payload["limitations"]}
    assert "limitations.comparability" in {item["code"] for item in payload["limitations"]}
    assert "progress" not in meaning


@pytest.mark.asyncio
async def test_missing_similar_reference_reports_unavailability_instead_of_a_conclusion(client):
    payload = (await _get_analysis(client, _FakeDB.NO_REFERENCE_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["available"] is False
    assert similar["sample_count"] == 0
    assert similar["limitations"] == ["no_comparable_reference"]
    assert "limitations.no_comparable_reference" in {item["code"] for item in payload["limitations"]}
    assert "historical comparison" not in payload["meaning"]["text"]


@pytest.mark.asyncio
async def test_baseline_observations_are_not_repeated_in_meaning_when_available(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    comparison = payload["comparison"]
    assert comparison["available"] is True
    meaning = payload["meaning"]["text"]
    assert f"{comparison['baseline_sample_count']}-session average" not in meaning
    assert "limitations.baseline_descriptive" in {item["code"] for item in payload["limitations"]}


@pytest.mark.asyncio
async def test_fixture_analyses_are_deterministic_across_repeated_calls(client):
    for workout_id in (_FakeDB.FIXTURE_A_ID, _FakeDB.FIXTURE_B_ID):
        first = (await _get_analysis(client, workout_id)).json()
        second = (await _get_analysis(client, workout_id)).json()
        assert first == second


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_fixture_analyses_are_localized_and_keep_the_numeric_facts(client, language):
    response = await _get_analysis_lang(client, _FakeDB.FIXTURE_A_ID, language)
    assert response.status_code == 200
    payload = response.json()
    assert "21.27 km" in payload["summary"]["text"]
    assert "5:43/km" in payload["summary"]["text"]
    assert payload["summary"]["code"] == "summary.long_structural"
    assert payload["advice"]["code"] == "advice.even_pacing"


@pytest.mark.asyncio
async def test_fixture_translations_actually_differ_between_languages(client):
    texts = {}
    for language in ("en", "fr", "es"):
        payload = (await _get_analysis_lang(client, _FakeDB.FIXTURE_A_ID, language)).json()
        texts[language] = payload["meaning"]["text"]
    assert len(set(texts.values())) == 3


@pytest.mark.asyncio
async def test_incomplete_workout_does_not_fabricate_missing_measurements(client):
    incomplete = _workout(
        "run-fixture-incomplete",
        user_id="user-a",
        date="2025-12-05T07:00:00+00:00",
        distance_km=6.0,
        duration_minutes=38,
    )
    await client.fake_db.workouts.insert_one(incomplete)
    payload = (await _get_analysis(client, "run-fixture-incomplete")).json()
    summary = payload["summary"]["text"]
    assert "You covered 6 km in 38 min." in summary
    assert "bpm" not in summary
    assert payload["physiology"]["available"] is False
    assert payload["physiology"]["avg_hr"] is None
    assert payload["physiology"]["hr_drift"] is None
    meaning = payload["meaning"]["text"]
    assert "bpm" not in meaning
    assert "Elevation gain" not in meaning
    assert "cadence" not in meaning.lower()


@pytest.mark.asyncio
async def test_similar_reference_is_exposed_without_breaking_the_v2_contract(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
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
        "limitations",
    }
    assert payload["comparison"]["baseline_period_days"] == 14
    assert isinstance(payload["comparison"]["similar"], dict)


@pytest.mark.asyncio
async def test_fixtures_are_not_readable_by_another_user(client):
    for workout_id in (_FakeDB.FIXTURE_A_ID, _FakeDB.FIXTURE_B_ID):
        response = await _get_analysis(client, workout_id, user_id="user-b")
        assert response.status_code == 404


def test_retrieve_similar_workouts_respects_sport_order_and_distance_tolerance():
    current = {"id": "c", "type": "run", "date": "2025-06-15T07:00:00+00:00", "distance_km": 10.0}
    candidates = [
        {"id": "same-sport-recent", "type": "run", "date": "2025-06-10T07:00:00+00:00", "distance_km": 11.0},
        {"id": "same-sport-older", "type": "run", "date": "2025-05-10T07:00:00+00:00", "distance_km": 9.0},
        {"id": "other-sport", "type": "cycle", "date": "2025-06-11T07:00:00+00:00", "distance_km": 10.5},
        {"id": "too-far-distance", "type": "run", "date": "2025-06-12T07:00:00+00:00", "distance_km": 14.0},
        {"id": "future", "type": "run", "date": "2025-06-16T07:00:00+00:00", "distance_km": 10.2},
        {"id": "outside-window", "type": "run", "date": "2024-06-10T07:00:00+00:00", "distance_km": 10.1},
    ]
    result = workout_analysis_v2.retrieve_similar_workouts(current, candidates)
    assert [item["id"] for item in result] == ["same-sport-recent", "same-sport-older"]


def test_retrieve_similar_workouts_separates_race_and_training_only_on_real_metadata():
    current = {
        "id": "c",
        "type": "run",
        "date": "2025-06-15T07:00:00+00:00",
        "distance_km": 10.0,
        "is_race": False,
    }
    candidates = [
        {"id": "race", "type": "run", "date": "2025-06-10T07:00:00+00:00", "distance_km": 10.0, "is_race": True},
        {"id": "training", "type": "run", "date": "2025-06-09T07:00:00+00:00", "distance_km": 10.0, "is_race": False},
        {"id": "unknown-nature", "type": "run", "date": "2025-06-08T07:00:00+00:00", "distance_km": 10.0},
        {"id": "race-named", "type": "run", "name": "Marathon de Paris", "date": "2025-06-07T07:00:00+00:00", "distance_km": 10.0},
    ]
    result = workout_analysis_v2.retrieve_similar_workouts(current, candidates)
    ids = [item["id"] for item in result]
    assert "race" not in ids
    # Nothing is inferred from the session name: the named session stays a candidate.
    assert ids == ["training", "unknown-nature", "race-named"]


def test_similar_search_constants_are_bounded():
    assert workout_analysis_v2.SIMILAR_DISTANCE_TOLERANCE_PCT == 30.0
    assert workout_analysis_v2.SIMILAR_HISTORY_WINDOW_DAYS == 180
    assert workout_analysis_v2.SIMILAR_MAX_RESULTS == 5
    assert workout_analysis_v2.SIMILAR_MIN_COMPARABLE_SAMPLE == 2


# ============================================================
# PR303 patch — factual-only analysis (no prescription, no generic baseline reading)
# ============================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("workout_id", [_FakeDB.FIXTURE_A_ID, _FakeDB.FIXTURE_B_ID, _FakeDB.NO_REFERENCE_ID])
async def test_analysis_never_prescribes_a_future_session(client, workout_id, language):
    payload = (await _get_analysis_lang(client, workout_id, language)).json()
    assert payload["advice"]["code"] in ALLOWED_ADVICE_CODES
    for block in ("summary", "meaning", "advice"):
        _assert_not_prescriptive(payload[block]["text"])


def test_no_advice_template_key_is_prescription_shaped():
    source = inspect.getsource(workout_analysis_v2)
    for banned in ("advice.recover_after_hard", "advice.maintain_easy", "advice.build_progressively"):
        assert banned not in source


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_advice_selection_is_driven_by_observed_facts_not_by_zone_absence(client, language):
    # Fixture A has a measured pace drop: the observation code wins over the zone limit.
    payload_a = (await _get_analysis_lang(client, _FakeDB.FIXTURE_A_ID, language)).json()
    assert payload_a["advice"]["code"] == "advice.even_pacing"
    # Fixture B has no split/drift/long signal: only then is the zone limit stated,
    # and it is stated as a limit of the analysis, never as an instruction.
    payload_b = (await _get_analysis_lang(client, _FakeDB.FIXTURE_B_ID, language)).json()
    assert payload_b["advice"]["code"] == "advice.hr_without_intensity"
    assert payload_a["advice"]["text"] != payload_b["advice"]["text"]


@pytest.mark.asyncio
async def test_generic_14_day_baseline_pace_and_hr_are_not_verbalized_in_meaning(client):
    # Fixture A's 14-day history mixes a 21 km session with much shorter runs.
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    comparison = payload["comparison"]
    # The baseline stays in the contract for compatibility...
    assert comparison["available"] is True
    assert comparison["avg_pace_min_km"]["baseline"] is not None
    meaning = payload["meaning"]["text"]
    # ...but its pace/HR deltas are never read as a performance comparison.
    assert "against that" not in meaning
    baseline_hr = comparison["avg_heart_rate"]["baseline"]
    if baseline_hr is not None:
        assert f"{baseline_hr}" not in meaning
    for banned in ("progression", "better session", "improved", "superior effort"):
        assert banned not in meaning.lower()


@pytest.mark.asyncio
async def test_baseline_distance_wording_stays_descriptive_and_only_claims_what_is_verified(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    meaning = payload["meaning"]["text"]
    assert "raw 2-session average of the last 14 days" not in meaning
    assert "limitations.baseline_descriptive" in {item["code"] for item in payload["limitations"]}
    assert payload["signals"]["volume"]["code"] == "above_recent"
    assert payload["signals"]["volume"]["text"] == "Distance above the recent average"


@pytest.mark.asyncio
async def test_baseline_without_any_comparable_session_yields_no_performance_claim(client):
    # NO_REFERENCE_ID has recent activity of very different distances but nothing comparable.
    payload = (await _get_analysis(client, _FakeDB.NO_REFERENCE_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["available"] is False
    assert similar["comparable"] is False
    meaning = payload["meaning"]["text"]
    assert "historical comparison" not in meaning
    assert "limitations.no_comparable_reference" in {item["code"] for item in payload["limitations"]}
    for banned in ("faster than", "slower than", "progression", "improved"):
        assert banned not in meaning.lower()
    _assert_not_prescriptive(meaning)


@pytest.mark.asyncio
async def test_unknown_session_nature_is_reported_and_blocks_strong_comparability(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    similar = payload["comparison"]["similar"]
    assert similar["sample_count"] == 2
    assert "session_nature_unknown" in similar["limitations"]
    assert similar["comparable"] is False
    meaning = payload["meaning"]["text"]
    assert "earlier session(s) of comparable distance" not in meaning
    assert similar["pace_difference_min_km"] is not None
    assert "limitations.session_nature_unknown" in {item["code"] for item in payload["limitations"]}


def test_explicit_race_metadata_excludes_incompatible_history():
    current = {
        "id": "current-race",
        "type": "run",
        "date": "2025-06-15T07:00:00+00:00",
        "distance_km": 10.0,
        "is_race": True,
    }
    candidates = [
        {"id": "hist-training", "type": "run", "date": "2025-06-10T07:00:00+00:00", "distance_km": 10.0, "is_race": False},
        {"id": "hist-race", "type": "run", "date": "2025-06-09T07:00:00+00:00", "distance_km": 10.0, "is_race": True},
    ]
    ids = [item["id"] for item in workout_analysis_v2.retrieve_similar_workouts(current, candidates)]
    assert ids == ["hist-race"]


def test_similar_reference_is_comparable_only_when_no_limitation_remains():
    current = {
        "id": "current",
        "type": "run",
        "date": "2025-06-15T07:00:00+00:00",
        "distance_km": 10.0,
        "avg_pace_min_km": 5.5,
        "avg_heart_rate": 151,
        "is_race": False,
    }
    candidates = [
        {"id": "h1", "type": "run", "date": "2025-06-10T07:00:00+00:00", "distance_km": 10.0, "avg_pace_min_km": 5.6, "avg_heart_rate": 150, "is_race": False},
        {"id": "h2", "type": "run", "date": "2025-06-09T07:00:00+00:00", "distance_km": 10.2, "avg_pace_min_km": 5.4, "avg_heart_rate": 152, "is_race": False},
    ]
    reference = workout_analysis_v2._build_similar_reference(current, candidates, "en")
    assert reference.available is True
    assert reference.sample_count == 2
    assert reference.limitations == []
    assert reference.comparable is True

    # Drop the explicit nature of one reference: comparability must fall back to False.
    candidates[1].pop("is_race")
    degraded = workout_analysis_v2._build_similar_reference(current, candidates, "en")
    assert degraded.limitations == ["session_nature_unknown"]
    assert degraded.comparable is False


# ============================================================
# PR303 final patch — per-metric coverage and verified baseline wording
# ============================================================


def _similar_candidate(workout_id: str, date: str, distance_km: float, **extra) -> dict:
    candidate = {
        "id": workout_id,
        "type": "run",
        "date": date,
        "distance_km": distance_km,
    }
    candidate.update(extra)
    return candidate


_CURRENT_FOR_COVERAGE = {
    "id": "coverage-current",
    "type": "run",
    "date": "2025-06-15T07:00:00+00:00",
    "distance_km": 10.0,
    "avg_pace_min_km": 5.5,
    "avg_heart_rate": 150,
}


def test_partial_pace_coverage_is_reported_with_its_own_sample_count():
    # 5 comparable sessions, only 2 of them carry a usable pace.
    candidates = [
        _similar_candidate("p1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8),
        _similar_candidate("p2", "2025-06-09T07:00:00+00:00", 10.1, avg_pace_min_km=5.6),
        _similar_candidate("p3", "2025-06-08T07:00:00+00:00", 10.2),
        _similar_candidate("p4", "2025-06-07T07:00:00+00:00", 9.9),
        _similar_candidate("p5", "2025-06-06T07:00:00+00:00", 10.3),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.sample_count == 5
    assert reference.pace_sample_count == 2
    assert reference.hr_sample_count == 0
    assert reference.avg_pace_min_km == pytest.approx((5.8 + 5.6) / 2, abs=0.01)
    assert "pace_sample_too_small" not in reference.limitations
    assert "hr_sample_too_small" in reference.limitations

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en"))
    # The pace sentence quotes the pace coverage, never the 5 sessions found.
    assert "Across 2 earlier session(s) of comparable distance carrying a usable pace" in text
    assert "Across 5 earlier session" not in text
    # No heart-rate claim can be made at all.
    assert "heart rate" not in text.lower()


def test_partial_hr_coverage_is_reported_and_flagged_as_insufficient():
    # 4 comparable sessions, only 1 of them carries a usable heart rate.
    candidates = [
        _similar_candidate("h1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8, avg_heart_rate=145),
        _similar_candidate("h2", "2025-06-09T07:00:00+00:00", 10.1, avg_pace_min_km=5.6),
        _similar_candidate("h3", "2025-06-08T07:00:00+00:00", 10.2, avg_pace_min_km=5.7),
        _similar_candidate("h4", "2025-06-07T07:00:00+00:00", 9.9, avg_pace_min_km=5.5),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.sample_count == 4
    assert reference.pace_sample_count == 4
    assert reference.hr_sample_count == 1
    assert reference.avg_heart_rate == pytest.approx(145.0, abs=0.01)
    assert "hr_sample_too_small" in reference.limitations
    assert "pace_sample_too_small" not in reference.limitations

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en"))
    assert "Average heart rate across 1 earlier session(s) of comparable distance carrying a usable heart rate" in text
    assert "Average heart rate across 4 earlier session" not in text
    # The insufficient heart-rate coverage is stated explicitly.
    assert "That heart-rate average rests on 1 of the 4 earlier session(s) found" in text


def test_comparable_history_without_any_pace_or_hr_invents_nothing():
    candidates = [
        _similar_candidate("n1", "2025-06-10T07:00:00+00:00", 10.0),
        _similar_candidate("n2", "2025-06-09T07:00:00+00:00", 10.1),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.available is True
    assert reference.sample_count == 2
    assert reference.pace_sample_count == 0
    assert reference.hr_sample_count == 0
    assert reference.avg_pace_min_km is None
    assert reference.avg_heart_rate is None
    assert reference.pace_difference_min_km is None
    assert reference.heart_rate_difference_bpm is None

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en")).lower()
    assert "average pace was" not in text
    assert "bpm" not in text


def test_distance_sample_count_tracks_real_distance_coverage():
    candidates = [
        _similar_candidate("d1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.6),
        _similar_candidate("d2", "2025-06-09T07:00:00+00:00", 10.1, avg_pace_min_km=5.7),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.distance_sample_count == 2
    assert reference.avg_distance_km == pytest.approx(10.05, abs=0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "es"])
async def test_baseline_wording_never_asserts_unverified_distance_mixing(client, language):
    payload = (await _get_analysis_lang(client, _FakeDB.FIXTURE_A_ID, language)).json()
    meaning = payload["meaning"]["text"]
    hedged = {
        "en": "may include sessions of different distances or natures",
        "fr": "peut inclure des séances de distances ou de nature différentes",
        "es": "puede incluir sesiones de distancias o naturalezas diferentes",
    }[language]
    asserted = {
        "en": "mixes sessions of different distances",
        "fr": "mélange des séances de distances différentes",
        "es": "mezcla sesiones de distancias diferentes",
    }[language]
    assert hedged not in meaning
    assert "limitations.baseline_descriptive" in {item["code"] for item in payload["limitations"]}
    assert asserted not in meaning


@pytest.mark.asyncio
async def test_identical_distance_baseline_is_not_described_as_mixed(client):
    # A 14-day history made only of identical distances must not be claimed as mixed.
    for index in range(2):
        await client.fake_db.workouts.insert_one(
            _workout(
                f"run-uniform-{index}",
                user_id="user-a",
                date=f"2025-06-1{index}T07:00:00+00:00",
                distance_km=12.0,
                duration_minutes=70,
                avg_pace_min_km=5.8,
            )
        )
    await client.fake_db.workouts.insert_one(
        _workout(
            "run-uniform-current",
            user_id="user-a",
            date="2025-06-14T07:00:00+00:00",
            distance_km=12.0,
            duration_minutes=70,
            avg_pace_min_km=5.8,
        )
    )
    payload = (await _get_analysis(client, "run-uniform-current")).json()
    meaning = payload["meaning"]["text"]
    assert "mixes sessions of different distances" not in meaning
    assert "average of the last" not in meaning
    assert "limitations.baseline_descriptive" in {item["code"] for item in payload["limitations"]}
    # Still no performance reading from the generic baseline.
    for banned in ("progression", "better session", "improved"):
        assert banned not in meaning.lower()


@pytest.mark.asyncio
async def test_mixed_distance_baseline_stays_descriptive_without_pace_or_hr_claims(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    comparison = payload["comparison"]
    assert comparison["available"] is True
    meaning = payload["meaning"]["text"]
    assert "may include sessions of different distances or natures" not in meaning
    assert "limitations.baseline_descriptive" in {item["code"] for item in payload["limitations"]}
    # The generic baseline never returns as a pace/HR comparison.
    assert "against that" not in meaning
    baseline_hr = comparison["avg_heart_rate"]["baseline"]
    if baseline_hr is not None:
        assert f"{baseline_hr}" not in meaning
    for banned in ("progression", "better session", "improved", "superior effort"):
        assert banned not in meaning.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("workout_id", [
    _FakeDB.CURRENT_ID,
    _FakeDB.HR_NO_ZONES_ID,
    _FakeDB.NO_HR_ID,
    _FakeDB.HIGH_ZONES_ID,
    _FakeDB.FIXTURE_A_ID,
    _FakeDB.FIXTURE_B_ID,
    _FakeDB.NO_REFERENCE_ID,
    _FakeDB.CADENCE_ID,
])
async def test_editorial_contract_is_short_localized_and_keeps_limits_accessible(client, language, workout_id):
    payload = (await _get_analysis_lang(client, workout_id, language)).json()
    meaning = payload["meaning"]["text"]
    assert len(meaning) <= 240
    assert meaning.count(".") <= 2
    assert not any(char.isdigit() for char in meaning)
    assert not any(observation in meaning for observation in workout_analysis_v2._comparison_observations(
        workout_analysis_v2.WorkoutAnalysisComparison.model_validate(payload["comparison"]), language
    ))
    codes = [item["code"] for item in payload["limitations"]]
    assert len(codes) == len(set(codes))
    assert "limitations.intensity" in codes
    if not payload["evidence"]["has_splits"]:
        assert "limitations.splits" in codes
    for item in payload["limitations"]:
        assert item["text"] != item["code"]
        assert item["text"] not in payload["advice"]["text"]
        assert item["text"] not in meaning
    advice = payload["advice"]
    if advice["available"] is False:
        assert advice["text"] == workout_analysis_v2._template(language, "advice.unavailable")
    else:
        assert advice["code"] not in {"advice.hr_without_intensity", "advice.no_hr"}
    for block in ("summary", "meaning", "advice"):
        _assert_not_prescriptive(payload[block]["text"])


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_no_interpretable_signal_has_honest_meaning_and_unavailable_advice(language):
    workout = _workout("minimal", user_id="u", date="2025-06-15", distance_km=8, duration_minutes=40)
    analysis = workout_analysis_v2.build_workout_analysis_v2(workout, [], language)
    assert analysis.meaning.code == "meaning.no_hr_no_pacing"
    assert analysis.advice.available is False
    assert analysis.advice.code == "advice.no_hr"
    assert analysis.advice.text == workout_analysis_v2._template(language, "advice.unavailable")
    assert {"limitations.heart_rate", "limitations.splits", "limitations.baseline",
            "limitations.no_comparable_reference", "limitations.session_nature_unknown"} <= {
        item.code for item in analysis.limitations
    }


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("split_analysis,hr_analysis,meaning_code,advice_code", [
    ({"pace_drop": 0.6}, {}, "meaning.pace_change", "advice.even_pacing"),
    ({"pace_drop": -0.6}, {}, "meaning.pace_change", "advice.even_pacing"),
    ({"negative_split": True}, {}, "meaning.negative_split", "advice.negative_split_confirmed"),
    ({"consistency_score": 95}, {}, "meaning.consistent_pacing", "advice.maintain_consistency"),
    ({}, {"hr_drift": 9}, "meaning.hr_drift", "advice.monitor_hr_drift"),
])
def test_meaning_selects_only_the_demonstrated_signal(language, split_analysis, hr_analysis, meaning_code, advice_code):
    workout = _workout(
        "observed", user_id="u", date="2025-06-15", distance_km=8, duration_minutes=40,
        split_analysis=split_analysis, hr_analysis=hr_analysis,
    )
    analysis = workout_analysis_v2.build_workout_analysis_v2(workout, [], language)
    assert analysis.meaning.code == meaning_code
    assert analysis.advice.code == advice_code
    assert analysis.advice.available is True
    assert analysis.signals.intensity.available is False
    assert len(analysis.meaning.text) <= 240
    if meaning_code == "meaning.pace_change":
        for unsupported_decline in ("pace drop", "perte d'allure", "pérdida de ritmo"):
            assert unsupported_decline not in analysis.advice.text


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_comparable_history_stays_separate_and_metrics_are_unchanged(language):
    workout = _workout(
        "complete", user_id="u", date="2025-06-15T07:00:00+00:00",
        distance_km=10, duration_minutes=60, avg_pace_min_km=6,
        avg_heart_rate=150, max_heart_rate=170,
        effort_zone_distribution={"z1": 20, "z2": 50, "z3": 20, "z4": 10, "z5": 0},
        km_splits=[{"pace_min_km": 5.9}, {"pace_min_km": 6.1}],
        split_analysis={"fastest_split_pace": 5.9, "slowest_split_pace": 6.1,
                        "pace_drop": 0.2, "negative_split": False, "consistency_score": 92},
        hr_analysis={"hr_drift": 6}, elevation_gain_m=210, avg_cadence_spm=172,
    )
    workout["is_race"] = False
    history = [
        dict(workout, id=f"previous-{index}", date=f"2025-06-0{index}T07:00:00+00:00")
        for index in (1, 2)
    ]
    analysis = workout_analysis_v2.build_workout_analysis_v2(workout, history, language)
    assert analysis.physiology.model_dump() == {
        "available": True, "avg_hr": 150, "max_hr": 170,
        "zone_distribution": {"z1": 20.0, "z2": 50.0, "z3": 20.0, "z4": 10.0, "z5": 0.0},
        "hr_drift": 6.0, "reason_unavailable": None,
    }
    assert analysis.pacing.model_dump() == {
        "available": True, "average_pace_min_km": 6.0, "average_speed_kmh": None,
        "fastest_split_min_km": 5.9, "slowest_split_min_km": 6.1, "pace_drop_min_km": 0.2,
        "negative_split": False, "consistency_score": 92.0, "variability": None,
        "reason_unavailable": None,
    }
    assert analysis.signals.intensity.available is False
    assert analysis.signals.intensity.code is None
    assert analysis.comparison.baseline_sample_count == 2
    assert analysis.comparison.similar.comparable is True
    assert analysis.comparison.similar.limitations == []
    assert analysis.comparison.similar.pace_difference_min_km == 0
    assert analysis.comparison.similar.heart_rate_difference_bpm == 0
    assert analysis.evidence.has_cadence and analysis.evidence.has_elevation
    assert "limitations.comparability" not in {item.code for item in analysis.limitations}
    assert analysis.meaning.code == "meaning.consistent_pacing"


@pytest.mark.asyncio
async def test_api_extension_accepts_legacy_payloads_and_preserves_code_text_consumers(client):
    payload = (await _get_analysis(client, _FakeDB.FIXTURE_A_ID)).json()
    assert isinstance(payload["advice"]["available"], bool)
    assert all(set(item) == {"code", "text"} for item in payload["limitations"])
    legacy_advice = workout_analysis_v2.AnalysisText.model_validate(payload["advice"])
    assert legacy_advice.text == payload["advice"]["text"]
    payload.pop("limitations")
    payload["advice"].pop("available")
    restored = workout_analysis_v2.WorkoutAnalysisV2Response.model_validate(payload)
    assert restored.advice.available is False
    assert restored.limitations == []
    assert restored.advice.text == legacy_advice.text
    restored.limitations.append(workout_analysis_v2.AnalysisText(code="test", text="test"))
    assert workout_analysis_v2.WorkoutAnalysisV2Response.model_validate(payload).limitations == []

# ============================================================
# PR #304 final patch — strict population alignment and metric validity
# ============================================================


def test_pace_sentence_uses_the_distance_of_the_pace_population_only():
    """P1 regression: the pace sentence must not mix two populations.

    Two sessions carry a pace (9.0 km and 10.0 km, average 9.5 km); three carry
    none (12.0, 12.5, 13.0 km). Quoting ``avg_distance_km`` here would announce
    the 11.3 km average of all five sessions next to a pace computed on two.
    """
    candidates = [
        _similar_candidate("a1", "2025-06-10T07:00:00+00:00", 9.0, avg_pace_min_km=5.8),
        _similar_candidate("a2", "2025-06-09T07:00:00+00:00", 10.0, avg_pace_min_km=5.6),
        _similar_candidate("a3", "2025-06-08T07:00:00+00:00", 12.0),
        _similar_candidate("a4", "2025-06-07T07:00:00+00:00", 12.5),
        _similar_candidate("a5", "2025-06-06T07:00:00+00:00", 13.0),
    ]
    current = dict(_CURRENT_FOR_COVERAGE, distance_km=11.0)
    reference = workout_analysis_v2._build_similar_reference(current, candidates, "en")

    assert reference.sample_count == 5
    assert reference.pace_sample_count == 2
    # The pace subset keeps its own distance average, distinct from the global one.
    assert reference.pace_avg_distance_km == pytest.approx(9.5, abs=0.001)
    assert reference.avg_distance_km == pytest.approx(11.3, abs=0.001)
    assert reference.pace_avg_distance_km != reference.avg_distance_km

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en"))
    assert "Across 2 earlier session(s) of comparable distance carrying a usable pace" in text
    assert "average 9.5 km" in text
    # The all-sessions average must never appear in the pace sentence.
    assert "11.3" not in text


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_pace_population_alignment_holds_in_every_language(language):
    candidates = [
        _similar_candidate("l1", "2025-06-10T07:00:00+00:00", 9.0, avg_pace_min_km=5.8),
        _similar_candidate("l2", "2025-06-09T07:00:00+00:00", 10.0, avg_pace_min_km=5.6),
        _similar_candidate("l3", "2025-06-08T07:00:00+00:00", 12.0),
        _similar_candidate("l4", "2025-06-07T07:00:00+00:00", 12.5),
        _similar_candidate("l5", "2025-06-06T07:00:00+00:00", 13.0),
    ]
    current = dict(_CURRENT_FOR_COVERAGE, distance_km=11.0)
    reference = workout_analysis_v2._build_similar_reference(current, candidates, language)
    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, language))
    assert "9.5" in text
    assert "11.3" not in text


def test_invalid_pace_values_are_excluded_from_coverage_and_average():
    candidates = [
        _similar_candidate("v1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8),
        _similar_candidate("v2", "2025-06-09T07:00:00+00:00", 10.0, avg_pace_min_km=5.6),
        _similar_candidate("v3", "2025-06-08T07:00:00+00:00", 10.2, avg_pace_min_km=None),
        _similar_candidate("v4", "2025-06-07T07:00:00+00:00", 9.9, avg_pace_min_km=0),
        _similar_candidate("v5", "2025-06-06T07:00:00+00:00", 10.3, avg_pace_min_km=-4.2),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    # Only the two well-formed paces are counted, and the average rests on them alone.
    assert reference.pace_sample_count == 2
    assert reference.avg_pace_min_km == pytest.approx(5.7, abs=0.001)
    assert reference.pace_avg_distance_km == pytest.approx(10.0, abs=0.001)


def test_non_finite_and_bool_pace_values_are_excluded_too():
    # SIMILAR_MAX_RESULTS caps the set at 5, so the remaining invalid kinds get
    # their own fixture rather than being silently truncated away.
    candidates = [
        _similar_candidate("vb1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8),
        _similar_candidate("vb2", "2025-06-09T07:00:00+00:00", 10.0, avg_pace_min_km=5.6),
        _similar_candidate("vb3", "2025-06-08T07:00:00+00:00", 10.2, avg_pace_min_km=float("nan")),
        _similar_candidate("vb4", "2025-06-07T07:00:00+00:00", 9.9, avg_pace_min_km=float("inf")),
        _similar_candidate("vb5", "2025-06-06T07:00:00+00:00", 10.3, avg_pace_min_km=True),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.pace_sample_count == 2
    assert reference.avg_pace_min_km == pytest.approx(5.7, abs=0.001)


def test_invalid_heart_rate_values_are_excluded_from_coverage_and_average():
    candidates = [
        _similar_candidate("w1", "2025-06-10T07:00:00+00:00", 10.0, avg_heart_rate=140),
        _similar_candidate("w2", "2025-06-09T07:00:00+00:00", 10.1, avg_heart_rate=150),
        _similar_candidate("w3", "2025-06-08T07:00:00+00:00", 10.2, avg_heart_rate=None),
        _similar_candidate("w4", "2025-06-07T07:00:00+00:00", 9.9, avg_heart_rate=0),
        _similar_candidate("w5", "2025-06-06T07:00:00+00:00", 10.3, avg_heart_rate=-10),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.hr_sample_count == 2
    assert reference.avg_heart_rate == pytest.approx(145.0, abs=0.001)


def test_non_finite_and_bool_heart_rate_values_are_excluded_too():
    candidates = [
        _similar_candidate("wb1", "2025-06-10T07:00:00+00:00", 10.0, avg_heart_rate=140),
        _similar_candidate("wb2", "2025-06-09T07:00:00+00:00", 10.1, avg_heart_rate=150),
        _similar_candidate("wb3", "2025-06-08T07:00:00+00:00", 10.2, avg_heart_rate=float("nan")),
        _similar_candidate("wb4", "2025-06-07T07:00:00+00:00", 9.9, avg_heart_rate=float("inf")),
        _similar_candidate("wb5", "2025-06-06T07:00:00+00:00", 10.3, avg_heart_rate=False),
    ]
    reference = workout_analysis_v2._build_similar_reference(_CURRENT_FOR_COVERAGE, candidates, "en")
    assert reference.hr_sample_count == 2
    assert reference.avg_heart_rate == pytest.approx(145.0, abs=0.001)


@pytest.mark.parametrize("invalid", [None, 0, -3.2, float("nan"), float("inf"), True])
def test_invalid_current_pace_produces_no_pace_difference(invalid):
    candidates = [
        _similar_candidate("c1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8),
        _similar_candidate("c2", "2025-06-09T07:00:00+00:00", 10.1, avg_pace_min_km=5.6),
    ]
    current = dict(_CURRENT_FOR_COVERAGE, avg_pace_min_km=invalid)
    reference = workout_analysis_v2._build_similar_reference(current, candidates, "en")
    assert reference.avg_pace_min_km is not None
    assert reference.pace_difference_min_km is None

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en"))
    assert "average pace was" not in text


@pytest.mark.parametrize("invalid", [None, 0, -10, float("nan"), float("inf"), True])
def test_invalid_current_heart_rate_produces_no_hr_difference(invalid):
    candidates = [
        _similar_candidate("d1", "2025-06-10T07:00:00+00:00", 10.0, avg_heart_rate=140),
        _similar_candidate("d2", "2025-06-09T07:00:00+00:00", 10.1, avg_heart_rate=150),
    ]
    current = dict(_CURRENT_FOR_COVERAGE, avg_heart_rate=invalid)
    reference = workout_analysis_v2._build_similar_reference(current, candidates, "en")
    assert reference.avg_heart_rate is not None
    assert reference.heart_rate_difference_bpm is None

    comparison = workout_analysis_v2.WorkoutAnalysisComparison(
        available=False,
        baseline_period_days=14,
        baseline_sample_count=0,
        similar=reference,
    )
    text = " ".join(workout_analysis_v2._comparison_observations(comparison, "en"))
    assert "Average heart rate across" not in text


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, False),
        (True, False),
        (False, False),
        (0, False),
        (0.0, False),
        (-1, False),
        (float("nan"), False),
        (float("inf"), False),
        (float("-inf"), False),
        ("5.5", False),
        (5.5, True),
        (150, True),
    ],
)
def test_valid_positive_number_rejects_only_impossible_values(value, expected):
    # No physiological calibration is applied: 1 bpm and 300 bpm are both "valid"
    # here. This helper only removes values that cannot be averaged honestly.
    assert workout_analysis_v2._valid_positive_number(value) is expected


def test_invalid_candidate_distance_never_enters_the_comparable_set():
    candidates = [
        _similar_candidate("x1", "2025-06-10T07:00:00+00:00", float("nan"), avg_pace_min_km=5.8),
        _similar_candidate("x2", "2025-06-09T07:00:00+00:00", 0, avg_pace_min_km=5.6),
        _similar_candidate("x3", "2025-06-08T07:00:00+00:00", 10.0, avg_pace_min_km=5.7),
    ]
    matches = workout_analysis_v2.retrieve_similar_workouts(_CURRENT_FOR_COVERAGE, candidates)
    assert [match["id"] for match in matches] == ["x3"]


def test_invalid_current_distance_yields_no_comparable_reference():
    candidates = [_similar_candidate("y1", "2025-06-10T07:00:00+00:00", 10.0, avg_pace_min_km=5.8)]
    current = dict(_CURRENT_FOR_COVERAGE, distance_km=float("nan"))
    assert workout_analysis_v2.retrieve_similar_workouts(current, candidates) == []
    reference = workout_analysis_v2._build_similar_reference(current, candidates, "en")
    assert reference.available is False
