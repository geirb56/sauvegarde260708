from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

import coach_service
from coach_service import generate_dynamic_training_plan


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field: str, direction: int):
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=direction < 0)
        return self

    def limit(self, n: int):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int] = None):
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def _ok(doc):
            for k, v in query.items():
                dv = doc.get(k)
                if isinstance(v, dict) and "$gte" in v:
                    if dv is None:
                        return False
                    if isinstance(dv, str) and isinstance(v["$gte"], str):
                        try:
                            dv_dt = datetime.fromisoformat(dv.replace("Z", "+00:00"))
                            gte_dt = datetime.fromisoformat(v["$gte"].replace("Z", "+00:00"))
                            if dv_dt < gte_dt:
                                return False
                            continue
                        except ValueError:
                            pass
                    if dv < v["$gte"]:
                        return False
                elif dv != v:
                    return False
            return True

        return _Cursor([dict(x) for x in self._docs if _ok(x)])

    async def find_one(self, query, projection=None):
        rows = await self.find(query, projection).to_list(None)
        return rows[0] if rows else None

    async def insert_one(self, doc):
        self._docs.append(dict(doc))

    async def update_one(self, query, update, upsert=False):
        found = await self.find_one(query)
        if found is None:
            if upsert:
                payload = dict(query)
                payload.update(update.get("$set", {}))
                self._docs.append(payload)
            return
        found.update(update.get("$set", {}))


class _FakeDB:
    def __init__(self, *, workouts=None, goal="SEMI", event_date=None, cycle_start_days_ago=21, ultra_distance=None):
        now = datetime.now(timezone.utc)
        cycle = {"user_id": "u1", "goal": goal, "start_date": now - timedelta(days=cycle_start_days_ago)}
        if ultra_distance is not None:
            cycle["target_distance_km"] = ultra_distance
        self.training_prefs = _Collection([{"user_id": "u1", "sessions_per_week": 4}])
        self.training_cycles = _Collection([cycle])
        self.workouts = _Collection(workouts or [])
        self.user_goals = _Collection(
            [{"user_id": "u1", "event_date": event_date, "target_distance_km": ultra_distance}]
            if event_date is not None or ultra_distance is not None else []
        )
        self.user_profiles = _Collection([])

    def __getattr__(self, name):
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _run(days_ago: int, km: float, *, user_id="u1"):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": user_id,
        "activity_type": "running",
        "distance_km": km,
        "moving_time": int(km * 6 * 60),
        "date": dt.isoformat(),
    }


@pytest.mark.asyncio
async def test_pipeline_normal_and_payload_compat():
    coach_service.clear_cache()
    workouts = [_run(d, 10.0) for d in (1, 3, 6, 8, 10, 13, 15, 17, 20, 22, 24, 27, 30, 33, 36)]
    db = _FakeDB(workouts=workouts)
    result = await generate_dynamic_training_plan(db, "u1")
    assert result["status"] == "active"
    assert result["context"]["training_state"] == "normal"
    assert result["debug_volume"]["target_basis"] == "distance"
    for key in ("plan", "week", "phase", "goal", "sessions_per_week", "current_week", "total_weeks", "status", "debug_volume"):
        assert key in result


@pytest.mark.asyncio
async def test_deep_reprise_duration_based_no_km_conversion():
    coach_service.clear_cache()
    db = _FakeDB(workouts=[_run(d, 9.0) for d in (30, 33, 36)])
    result = await generate_dynamic_training_plan(db, "u1")
    wt = result["context"]["weekly_target_v2"]
    assert result["context"]["training_state"] == "deep_reprise"
    assert wt["target_basis"] == "duration"
    assert wt["allow_intensity"] is False
    assert result["plan"]["weekly_km"] is None
    assert result["plan"]["weekly_minutes"] is not None


@pytest.mark.asyncio
async def test_partial_reprise_and_reprise_exit_states():
    coach_service.clear_cache()
    partial_workouts = (
        [_run(d, 12.0) for d in (8, 10, 12, 14, 16, 18, 20, 22)] +
        [_run(d, 2.0) for d in (1, 3)]
    )
    partial = await generate_dynamic_training_plan(_FakeDB(workouts=partial_workouts), "u1")
    assert partial["context"]["training_state"] == "partial_reprise"
    assert partial["context"]["weekly_target_v2"]["allow_intensity"] is False

    coach_service.clear_cache()
    reprise_exit_workouts = [_run(d, 6.0) for d in (2, 5, 8, 12, 18)]
    reprise_exit = await generate_dynamic_training_plan(_FakeDB(workouts=reprise_exit_workouts), "u1")
    assert reprise_exit["context"]["training_state"] == "reprise_exit"


@pytest.mark.asyncio
async def test_reconciliation_keep_insufficient_response():
    coach_service.clear_cache()
    workouts = [_run(d, 9.0) for d in (2, 5, 8, 12)]  # 4 runs => insufficient
    result = await generate_dynamic_training_plan(_FakeDB(workouts=workouts), "u1", sessions_override=6)
    rec = result["context"]["weekly_reconciliation_v2"]
    assert rec["action"] == "KEEP"
    assert rec["response_status"] == "insufficient"


@pytest.mark.asyncio
async def test_reconciliation_reduces_before_workout_generator(monkeypatch):
    coach_service.clear_cache()
    captured = {}
    original = coach_service.build_weekly_plan

    def _capture(*, weekly_target, **kwargs):
        captured["sessions"] = weekly_target.target_sessions
        captured["target_km"] = weekly_target.target_km
        return original(weekly_target=weekly_target, **kwargs)

    monkeypatch.setattr(coach_service, "build_weekly_plan", _capture)
    workouts = [_run(d, 10.0) for d in (1, 2, 4, 6)] + [_run(20, 2.0)]
    result = await generate_dynamic_training_plan(_FakeDB(workouts=workouts), "u1", sessions_override=6)
    rec = result["context"]["weekly_reconciliation_v2"]
    assert rec["action"] in {"REDUCE_VOLUME", "REDUCE_FREQUENCY", "REDUCE_BOTH"}
    assert captured["sessions"] == rec["reconciled_target"]["target_sessions"]
    assert captured["target_km"] == rec["reconciled_target"]["target_km"]
    assert rec["reconciled_target"]["target_sessions"] <= rec["original_target"]["target_sessions"]
    if rec["reconciled_target"]["target_km"] is not None:
        assert rec["reconciled_target"]["target_km"] <= rec["original_target"]["target_km"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_goal,expected_type,expected_goal",
    [
        ("MAINTENANCE", "maintenance", "MAINTENANCE"),
        ("5K", "5k", "5K"),
        ("10K", "10k", "10K"),
        ("SEMI", "half_marathon", "SEMI"),
        ("MARATHON", "marathon", "MARATHON"),
    ],
)
async def test_goal_mapping_non_ultra(raw_goal, expected_type, expected_goal):
    coach_service.clear_cache()
    workouts = [_run(d, 10.0) for d in (1, 3, 8, 10, 15)]
    result = await generate_dynamic_training_plan(_FakeDB(workouts=workouts, goal=raw_goal), "u1")
    assert result["goal"] == expected_goal
    assert result["goal_config"]["goal_type"] == expected_type


@pytest.mark.asyncio
async def test_goal_mapping_ultra_valid_and_missing_distance():
    coach_service.clear_cache()
    workouts = [_run(d, 10.0) for d in (1, 3, 8, 10, 15)]
    ok = await generate_dynamic_training_plan(
        _FakeDB(workouts=workouts, goal="ULTRA", ultra_distance=65.0),
        "u1",
    )
    assert ok["goal"] == "ULTRA"
    assert ok["goal_config"]["goal_type"] == "ultra"
    assert ok["goal_config"]["target_distance_km"] == 65.0

    missing = await generate_dynamic_training_plan(_FakeDB(workouts=workouts, goal="ULTRA"), "u1")
    assert missing["status"] == "unavailable"
    assert missing["context"]["error"] == "ULTRA_TARGET_DISTANCE_REQUIRED"


def test_anti_legacy_generate_dynamic_path():
    source = coach_service.generate_dynamic_training_plan.__code__.co_names
    forbidden = {
        "resolve_reprise_plan",
        "compute_target_km",
        "compute_long_run_km",
        "determine_target_load",
        "_deterministic_plan",
    }
    assert forbidden.isdisjoint(set(source))
