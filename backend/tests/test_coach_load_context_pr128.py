"""PR #128 — coach/training context legacy load cleanup."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import coach_service
from training_engine import build_training_context
from training_v2.training_load import build_training_load


class _Cursor:
    def __init__(self, docs: List[dict]) -> None:
        self._docs = list(docs)

    def sort(self, field: str, direction: int) -> "_Cursor":
        reverse = direction < 0
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=reverse)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
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
                doc_value = doc.get(key)
                if isinstance(value, dict) and "$gte" in value:
                    if doc_value is None or doc_value < value["$gte"]:
                        return False
                    continue
                if doc_value != value:
                    return False
            return True

        return _Cursor([dict(doc) for doc in self._docs if _match(doc)])

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        for doc in (await self.find(query, projection).to_list(length=None)):
            return doc
        return None

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        existing = await self.find_one(query)
        if existing is None:
            if upsert:
                payload = dict(query)
                payload.update(update.get("$set", {}))
                self._docs.append(payload)
            return
        existing.update(update.get("$set", {}))


class _FakeDB:
    def __init__(
        self,
        *,
        workouts: Optional[List[dict]] = None,
        garmin_activities: Optional[List[dict]] = None,
        training_cycles: Optional[List[dict]] = None,
    ) -> None:
        self.training_prefs = _Collection([])
        self.training_cycles = _Collection(training_cycles or [])
        self.workouts = _Collection(workouts or [])
        self.garmin_activities = _Collection(garmin_activities or [])
        self.user_goals = _Collection([])

    def __getattr__(self, name: str) -> _Collection:
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _workout(user_id: str, days_ago: int, *, distance_km: float = 10.0, duration_minutes: float = 50.0) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "date": dt.isoformat(),
        "activity_type": "Run",
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
    }


def _garmin_activity(user_id: str, days_ago: int, duration_s: Optional[float]) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    doc = {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": dt.date().isoformat() + "T08:00:00",
    }
    if duration_s is not None:
        doc["duration"] = duration_s
    return doc


def test_build_training_context_keeps_legacy_metrics_absent():
    context = build_training_context({"load_7": 300.0, "load_28": 1200.0}, weekly_km=30.0)

    assert context["load_7"] == 300.0
    assert context["load_28"] == 1200.0
    assert context["weekly_km"] == 30.0
    assert context["acwr"] is None
    assert context["tsb"] is None
    assert context["ctl"] is None
    assert context["atl"] is None
    assert "risk_level" not in context


@pytest.mark.asyncio
async def test_generate_dynamic_training_plan_injects_v2_acwr():
    user_id = "coach-user-a"
    workouts = [_workout(user_id, d) for d in range(28)]
    garmin_activities = [_garmin_activity(user_id, d, 1800.0) for d in range(28)]
    fake_db = _FakeDB(
        workouts=workouts,
        garmin_activities=garmin_activities,
        training_cycles=[{"user_id": user_id, "goal": "SEMI", "start_date": datetime.now(timezone.utc)}],
    )

    with patch.object(
        coach_service,
        "generate_cycle_week",
        AsyncMock(return_value=([{"type": "Footing", "details": "easy"}], True, {})),
    ):
        result = await coach_service.generate_dynamic_training_plan(fake_db, user_id)

    expected = build_training_load(garmin_activities, datetime.now(timezone.utc).date()).acwr
    assert result["context"]["acwr"] == expected
    assert result["context"]["tsb"] is None


@pytest.mark.asyncio
async def test_generate_dynamic_training_plan_without_snapshot_keeps_acwr_none():
    user_id = "coach-user-empty"
    workouts = [_workout(user_id, d) for d in range(10)]
    fake_db = _FakeDB(
        workouts=workouts,
        garmin_activities=[],
        training_cycles=[{"user_id": user_id, "goal": "SEMI", "start_date": datetime.now(timezone.utc)}],
    )

    with patch.object(
        coach_service,
        "generate_cycle_week",
        AsyncMock(return_value=([{"type": "Footing", "details": "easy"}], True, {})),
    ):
        result = await coach_service.generate_dynamic_training_plan(fake_db, user_id)

    assert result["context"]["acwr"] is None
    assert result["context"]["tsb"] is None


def test_legacy_training_load_engine_removed():
    assert not (_BACKEND / "engine" / "training_load_engine.py").exists()
