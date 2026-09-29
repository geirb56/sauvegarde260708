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
from garmin.service import activity_to_workout  # noqa: E402


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
                    elif operator == "$lte":
                        if actual is None or actual > operator_value:
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
    pace_stats: dict | None = None,
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
        "pace_stats": pace_stats or {},
        "avg_cadence_spm": avg_cadence_spm,
        "cadence_analysis": cadence_analysis or {},
        "elevation_gain_m": elevation_gain_m,
        "data_source": "garmin",
    }


@pytest.fixture
def workout_a() -> dict:
    return _workout(
        "run-half-distance",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=21.27,
        duration_minutes=122,
        avg_heart_rate=160,
        max_heart_rate=178,
        avg_pace_min_km=5.72,
    )


@pytest.fixture
def workout_b() -> dict:
    return _workout(
        "run-short-distance",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=10.18,
        duration_minutes=71,
        avg_heart_rate=127,
        max_heart_rate=145,
        avg_pace_min_km=6.98,
    )


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
                date="2026-01-20T07:00:00+00:00",
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
                "user-b-nearby-run",
                user_id="user-b",
                date="2026-01-15T07:00:00+00:00",
                distance_km=9.0,
                duration_minutes=50,
                avg_pace_min_km=5.55,
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
                "run-outside-distance",
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


def test_required_run_fixtures_produce_distinct_fact_based_analysis(workout_a, workout_b):
    analysis_a = workout_analysis_v2.build_workout_analysis_v2(workout_a, [], "en")
    analysis_b = workout_analysis_v2.build_workout_analysis_v2(workout_b, [], "en")

    assert analysis_a.summary.text != analysis_b.summary.text
    assert analysis_a.meaning.text != analysis_b.meaning.text
    assert analysis_a.advice.text != analysis_b.advice.text
    assert "21.27 km" in analysis_a.summary.text
    assert "122 min" in analysis_a.summary.text
    assert "5:43/km" in analysis_a.summary.text
    assert "160 bpm" in analysis_a.summary.text
    assert "10.18 km" in analysis_b.summary.text
    assert "71 min" in analysis_b.summary.text
    assert "6:59/km" in analysis_b.summary.text
    assert "127 bpm" in analysis_b.summary.text
    for result in (analysis_a, analysis_b):
        assert result.evidence.has_hr_zones is False
        assert result.signals.intensity.available is False
        assert result.pacing.fastest_split_min_km is None
        assert "fastest split" not in result.meaning.text.lower()
        assert "individualized heart-rate zones" not in result.advice.text.lower()


def test_fact_based_analysis_is_localized_to_supported_languages(workout_a):
    analyses = {
        language: workout_analysis_v2.build_workout_analysis_v2(workout_a, [], language)
        for language in ("fr", "en", "es")
    }

    assert "distance : 21,27 km" in analyses["fr"].summary.text
    assert "allure moyenne : 5:43/km" in analyses["fr"].summary.text
    assert "distance: 21.27 km" in analyses["en"].summary.text
    assert "distancia: 21,27 km" in analyses["es"].summary.text
    assert len({result.advice.text for result in analyses.values()}) == 3


def test_missing_session_values_remain_unknown():
    workout = _workout(
        "run-incomplete",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=None,
        duration_minutes=None,
    )
    workout["avg_heart_rate"] = None
    workout["max_heart_rate"] = None
    workout["avg_pace_min_km"] = None

    result = workout_analysis_v2.build_workout_analysis_v2(workout, [], "en")

    assert result.pacing.average_pace_min_km is None
    assert result.physiology.avg_hr is None
    assert result.comparison.available is False
    assert result.comparison.baseline_sample_count == 0
    assert "0 km" not in result.summary.text
    assert "0 min" not in result.summary.text


def test_split_hr_drift_cadence_and_elevation_are_reported_without_causal_claims():
    workout = _workout(
        "run-with-observations",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=10.0,
        duration_minutes=60,
        avg_heart_rate=150,
        max_heart_rate=170,
        avg_pace_min_km=6.0,
        km_splits=[
            {"km": 1, "pace_min_km": 5.5},
            {"km": 2, "pace_min_km": 6.2},
        ],
        split_analysis={
            "fastest_split_pace": 5.5,
            "slowest_split_pace": 6.2,
            "pace_drop": 0.3,
            "negative_split": True,
            "consistency_score": 91,
        },
        pace_stats={"pace_variability": 0.2},
        hr_analysis={"hr_drift": 6},
        avg_cadence_spm=176,
        elevation_gain_m=120,
    )

    result = workout_analysis_v2.build_workout_analysis_v2(workout, [], "en")

    assert "fastest split: 5:30/km" in result.meaning.text
    assert "slowest split: 6:12/km" in result.meaning.text
    assert "a negative split was recorded" in result.meaning.text
    assert "recorded HR drift: 6 bpm" in result.meaning.text
    assert "average cadence: 176 spm" in result.meaning.text
    assert "elevation gain: 120 m" in result.meaning.text
    assert "dehydrat" not in result.meaning.text.lower()
    assert "fatigue" not in result.meaning.text.lower()
    assert "170-180" not in result.advice.text


def test_garmin_derived_workout_preserves_available_analysis_observations():
    workout = activity_to_workout(
        {
            "external_id": "garmin-activity",
            "activity_type": "running",
            "start_time": "2026-09-20T07:00:00+00:00",
            "distance": 21_270,
            "duration": 7_320,
            "pace_seconds_per_km": 343.2,
            "avg_hr": 160,
            "garmin_activity": {
                "max_hr": 178,
                "average_run_cadence": 176,
                "elevation_gain": 120,
            },
        },
        "user-a",
    )

    result = workout_analysis_v2.build_workout_analysis_v2(workout, [], "en")

    assert workout["max_heart_rate"] == 178
    assert workout["avg_cadence_spm"] == 176
    assert workout["elevation_gain_m"] == 120
    assert "maximum HR: 178 bpm" in result.summary.text
    assert "average cadence: 176 spm" in result.meaning.text
    assert "elevation gain: 120 m" in result.meaning.text


def test_history_comparison_uses_prior_similar_distance_sessions_without_claiming_progress():
    current = _workout(
        "run-current",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=10.0,
        duration_minutes=60,
        avg_heart_rate=150,
        avg_pace_min_km=5.8,
    )
    history = [
        _workout(
            "run-prior-1",
            user_id="user-a",
            date="2026-09-10T07:00:00+00:00",
            distance_km=9.0,
            duration_minutes=55,
            avg_heart_rate=145,
            avg_pace_min_km=6.0,
        ),
        _workout(
            "run-prior-2",
            user_id="user-a",
            date="2026-09-01T07:00:00+00:00",
            distance_km=11.0,
            duration_minutes=65,
            avg_heart_rate=148,
            avg_pace_min_km=5.9,
        ),
        _workout(
            "run-future-similar",
            user_id="user-a",
            date="2026-09-21T07:00:00+00:00",
            distance_km=10.0,
            duration_minutes=60,
            avg_pace_min_km=5.5,
        ),
    ]

    result = workout_analysis_v2.build_workout_analysis_v2(current, history, "en")

    assert result.comparison.available is True
    assert result.comparison.baseline_sample_count == 2
    assert result.comparison.baseline_period_days == 90
    assert "2 selected prior comparable sessions (maximum 3) in the last 90 days" in result.meaning.text
    assert "reference average 5:57/km" in result.meaning.text
    assert "not evidence by itself of progression" in result.meaning.text


def test_one_comparable_session_is_not_enough_for_a_baseline():
    current = _workout(
        "run-current",
        user_id="user-a",
        date="2026-09-20T07:00:00+00:00",
        distance_km=10.0,
        duration_minutes=60,
    )
    prior = _workout(
        "run-prior",
        user_id="user-a",
        date="2026-09-10T07:00:00+00:00",
        distance_km=9.0,
        duration_minutes=55,
    )

    result = workout_analysis_v2.build_workout_analysis_v2(current, [prior], "en")

    assert result.comparison.available is False
    assert result.comparison.baseline_sample_count == 1
    assert result.comparison.distance_km is None
    assert "at least 2" in result.comparison.reason_unavailable


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
    assert lowered_summary.startswith("standard-duration session completed.")
    for forbidden in ("steady", "consistent", "regular"):
        assert forbidden not in lowered_summary


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
    assert payload["comparison"]["baseline_sample_count"] == 3
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
    assert history_query["date"] == {"$gte": "2026-06-12", "$lt": "2026-09-10"}
    assert history_query["distance_km"] == {"$gte": 7.0, "$lte": 13.0}
    assert client.fake_db.workouts.to_list_lengths[-1] == 200


@pytest.mark.asyncio
async def test_endpoint_candidate_query_does_not_require_old_same_type_history(client):
    client.fake_db.workouts.find_queries.clear()
    response = await _get_analysis(client, _FakeDB.MIXED_DATE_ID)
    assert response.status_code == 200
    candidate_docs = [
        doc for doc in client.fake_db.workouts._docs
        if client.fake_db.workouts._matches(doc, client.fake_db.workouts.find_queries[-1])
    ]
    candidate_ids = {doc["id"] for doc in candidate_docs}
    assert "run-outside-distance" not in candidate_ids
    assert {"run-mixed-prev-z", "run-mixed-prev-offset"} <= candidate_ids
    assert "run-mixed-future" not in candidate_ids


@pytest.mark.asyncio
async def test_future_workout_does_not_change_older_workout_analysis(client):
    response = await _get_analysis(client, _FakeDB.CURRENT_ID)
    payload = response.json()
    assert payload["comparison"]["baseline_sample_count"] == 3


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
    }
    assert payload["signals"]["intensity"]["available"] is False
    assert payload["summary"]["text"]
    assert isinstance(payload["evidence"]["has_baseline"], bool)
    assert payload["comparison"]["baseline_period_days"] == 90
