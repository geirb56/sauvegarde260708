from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from engine.readiness_engine import compute_readiness
from terra_integration import _workout_to_v2_activity, computeRecoveryScore, computeTrainingLoad, generateWorkoutRecommendation
from training_v2.training_load import build_training_load


class _Collection:
    def __init__(self, docs: Optional[list[dict]] = None) -> None:
        self._docs = list(docs or [])

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        for doc in self._docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for index, doc in enumerate(self._docs):
            if all(doc.get(key) == value for key, value in query.items()):
                merged = dict(doc)
                merged.update(payload)
                self._docs[index] = merged
                return
        if upsert:
            self._docs.append(payload)

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> "_Cursor":
        def _match(doc: dict) -> bool:
            for key, value in (query or {}).items():
                doc_value = doc.get(key)
                if isinstance(value, dict) and "$gte" in value:
                    if doc_value is None or doc_value < value["$gte"]:
                        return False
                    continue
                if doc_value != value:
                    return False
            return True

        docs = [dict(doc) for doc in self._docs if _match(doc)]
        if projection:
            include = {key for key, enabled in projection.items() if enabled}
            docs = [{key: doc.get(key) for key in include if key in doc} for doc in docs]
        return _Cursor(docs)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = list(docs)

    async def to_list(self, length: Optional[int] = None) -> list[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _FakeDB:
    def __init__(
        self,
        *,
        daily_metrics: Optional[list[dict]] = None,
        baselines: Optional[list[dict]] = None,
        workouts: Optional[list[dict]] = None,
    ) -> None:
        self.daily_metrics = _Collection(daily_metrics)
        self.baselines = _Collection(baselines)
        self.workouts = _Collection(workouts)
        self.training_load = _Collection()
        self.recovery_scores = _Collection()
        self.workout_recommendations = _Collection()


def test_workout_without_type_does_not_contribute_to_training_load_v2():
    activity = _workout_to_v2_activity(
        {
            "date": "2026-08-06T08:00:00",
            "duration_minutes": 45.0,
            "distance_km": 10.0,
        }
    )

    snapshot = build_training_load([activity], date(2026, 8, 6))

    assert activity["activity_type"] is None
    assert snapshot.acute_load_7d == 0.0
    assert snapshot.activities_7d == 0
    assert snapshot.acwr is None


@pytest.mark.asyncio
async def test_training_load_score_none_is_never_replaced_by_70():
    today = datetime.now(timezone.utc).date().isoformat()
    db = _FakeDB(
        daily_metrics=[
            {
                "user_id": "terra-user",
                "date": today,
                "hrv": 80.0,
                "sleep_quality": 60.0,
            }
        ],
        baselines=[{"user_id": "terra-user", "baseline_hrv": 80.0}],
    )

    with patch(
        "terra_integration.computeTrainingLoad",
        AsyncMock(return_value={"training_load_score": None, "acwr": None, "status": "unavailable"}),
    ):
        result = await computeRecoveryScore("terra-user", db)

    assert result["readiness"] == pytest.approx(82.9, abs=0.05)
    assert result["recovery_score"] == pytest.approx(82.9, abs=0.05)
    assert result["fatigue_score"] == pytest.approx(17.1, abs=0.05)
    assert result["status"] == "ready"
    assert result["readiness"] != 70.0


@pytest.mark.asyncio
async def test_workout_without_type_does_not_contribute_to_compute_training_load():
    today = datetime.now(timezone.utc)
    db = _FakeDB(
        workouts=[
            {
                "user_id": "terra-user",
                "date": today.isoformat(),
                "duration_minutes": 45.0,
                "distance_km": 10.0,
            }
        ]
    )

    result = await computeTrainingLoad("terra-user", db)

    assert result["acwr"] is None
    assert result["training_load_score"] is None
    assert result["status"] == "unavailable"


@pytest.mark.asyncio
async def test_no_fictitious_load_fallback_when_legacy_recovery_is_unavailable():
    db = _FakeDB()

    with (
        patch(
            "terra_integration.computeRecoveryScore",
            AsyncMock(
                return_value={
                    "readiness": None,
                    "recovery_score": None,
                    "fatigue_score": None,
                    "status": "unavailable",
                }
            ),
        ),
        patch(
            "terra_integration.computeTrainingLoad",
            AsyncMock(return_value={"training_load_score": None, "acwr": None, "status": "unavailable"}),
        ),
    ):
        result = await generateWorkoutRecommendation("terra-user", db)

    assert result["type"] is None
    assert result["duration"] is None
    assert result["intensity"] is None
    assert result["readiness"] is None
    assert result["acwr"] is None


@pytest.mark.asyncio
async def test_real_terra_load_behavior_is_preserved():
    today_dt = datetime.now(timezone.utc)
    today = today_dt.date().isoformat()
    db = _FakeDB(
        daily_metrics=[
            {
                "user_id": "terra-user",
                "date": today,
                "hrv": 80.0,
                "sleep_quality": 60.0,
            }
        ],
        baselines=[{"user_id": "terra-user", "baseline_hrv": 80.0}],
        workouts=[
            {
                "user_id": "terra-user",
                "date": (today_dt).isoformat(),
                "activity_type": "running",
                "duration_minutes": 45.0,
                "distance_km": 10.0,
            },
            {
                "user_id": "terra-user",
                "date": (today_dt).isoformat(),
                "activity_type": "running",
                "duration_minutes": 60.0,
                "distance_km": 12.0,
            },
        ],
    )

    load = await computeTrainingLoad("terra-user", db)
    result = await computeRecoveryScore("terra-user", db)

    expected = compute_readiness(
        training_load_score=load["training_load_score"],
        sleep_score=60.0,
        hrv_score=100.0,
        rhr_today=None,
        baseline_rhr=None,
    )
    assert load["training_load_score"] is not None
    assert result["readiness"] == expected
    assert result["recovery_score"] == expected
    assert result["status"] == ("ready" if expected >= 75 else "moderate" if expected >= 50 else "fatigued")
