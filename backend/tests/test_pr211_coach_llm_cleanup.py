from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

import coach_service
import llm_coach


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, field: str, direction: int):
        self._docs.sort(key=lambda d: d.get(field) or "", reverse=direction < 0)
        return self

    async def to_list(self, length: Optional[int] = None):
        return list(self._docs if length is None else self._docs[:length])


class _Collection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def _ok(doc):
            for k, v in query.items():
                dv = doc.get(k)
                if isinstance(v, dict) and "$gte" in v:
                    if dv is None or dv < v["$gte"]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if dv == v["$ne"]:
                        return False
                elif dv != v:
                    return False
            return True

        return _Cursor([dict(x) for x in self._docs if _ok(x)])

    async def find_one(self, query, projection=None, sort=None):
        rows = await self.find(query, projection).to_list(None)
        if sort:
            field, direction = sort[0]
            rows.sort(key=lambda d: d.get(field) or "", reverse=direction < 0)
        return rows[0] if rows else None

    async def insert_one(self, doc):
        self._docs.append(dict(doc))

    async def update_one(self, query, update, upsert=False):
        existing = await self.find_one(query)
        if existing is None:
            if upsert:
                payload = dict(query)
                payload.update(update.get("$set", {}))
                self._docs.append(payload)
            return
        existing.update(update.get("$set", {}))


class _FakeDB:
    def __init__(self, workouts=None, garmin_activities=None, garmin_vo2max=None):
        now = datetime.now(timezone.utc)
        self.training_prefs = _Collection([{"user_id": "u1", "sessions_per_week": 4}])
        self.training_cycles = _Collection([{"user_id": "u1", "goal": "SEMI", "start_date": now - timedelta(days=21)}])
        self.workouts = _Collection(workouts or [])
        self.user_goals = _Collection([])
        self.user_profiles = _Collection([])
        self.garmin_activities = _Collection(garmin_activities or [])
        self.garmin_vo2max = _Collection(garmin_vo2max or [])

    def __getattr__(self, name):
        col = _Collection([])
        object.__setattr__(self, name, col)
        return col


def _workout(days_ago: int, km: float):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "user_id": "u1",
        "activity_type": "running",
        "distance_km": km,
        "moving_time": int(km * 6 * 60),
        "date": dt.isoformat(),
    }


def test_no_runtime_generate_cycle_week_callers_in_backend_sources():
    backend = Path(__file__).resolve().parent.parent
    offenders = []
    for py in backend.rglob("*.py"):
        if "/tests/" in py.as_posix():
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "generate_cycle_week":
                    offenders.append(str(py))
                if isinstance(node.func, ast.Attribute) and node.func.attr == "generate_cycle_week":
                    offenders.append(str(py))
    assert not offenders


def test_llm_and_coach_sources_have_no_legacy_training_engine_links():
    llm_source = Path(llm_coach.__file__).read_text(encoding="utf-8")
    coach_source = Path(coach_service.__file__).read_text(encoding="utf-8")
    assert "from training_engine import" not in llm_source
    assert "generate_cycle_week" not in coach_source


def test_no_legacy_performance_fallback_formulas_in_coach_service():
    source = Path(coach_service.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "_compute_legacy_performance_compatibility" not in source
    assert "_readiness_compatibility_score" not in source
    assert "estimated_vma = 12.0" not in source
    legacy_keys = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert "readiness_score" not in legacy_keys


def test_coach_service_has_no_perf_vma_consumers():
    tree = ast.parse(Path(coach_service.__file__).read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"vma", "vma_kmh"}:
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id == "perf":
                raise AssertionError("coach_service still consumes perf.vma/perf.vma_kmh")

    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "predict_races" not in calls


def test_server_coach_analyze_no_hr_speed_vma_exposure():
    server_path = Path(__file__).resolve().parent.parent / "server.py"
    source = server_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = next(
        (n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "analyze_with_coach"),
        None,
    )
    assert target is not None

    fn_src = ast.get_source_segment(source, target) or ""
    assert "perf.vma" not in fn_src
    assert "vma_kmh" not in fn_src
    assert "Estimated VMA:" not in fn_src
    assert "predict_races(" in fn_src
    assert "compute_training_paces(" in fn_src
    assert "garmin_vo2max" in fn_src


@pytest.mark.asyncio
async def test_generate_dynamic_plan_handles_missing_performance_signals():
    coach_service.clear_cache()
    workouts = [_workout(d, 10.0) for d in (1, 3, 6, 8, 10, 13, 15)]
    db = _FakeDB(workouts=workouts, garmin_activities=[], garmin_vo2max=[])
    result = await coach_service.generate_dynamic_training_plan(db, "u1")

    assert result["plan"] is not None
    assert result["vma"] is None
    assert result["vo2max"] is None
    assert result["paces"] == {}
    assert "goal_compatibility_score" in result
    assert "readiness_score" not in result
    assert "goal_compatibility_score" in result["context"]
    assert "readiness_score" not in result["context"]


@pytest.mark.asyncio
async def test_canonical_loader_keeps_vma_none_and_preserves_vo2max_and_paces(monkeypatch):
    coach_service.clear_cache()
    db = _FakeDB(
        workouts=[],
        garmin_activities=[{"user_id": "u1", "activity_type": "running", "start_time": datetime.now(timezone.utc).isoformat()}],
        garmin_vo2max=[{"user_id": "u1", "date": "2026-08-01", "vo2max_running": 51.2}],
    )

    monkeypatch.setattr(coach_service, "mongo_garmin_activities_to_domain", lambda _docs: [SimpleNamespace()])
    monkeypatch.setattr(
        coach_service,
        "compute_training_paces",
        lambda *_args, **_kwargs: SimpleNamespace(
            easy=SimpleNamespace(lower_str="5:50", upper_str="6:20"),
            marathon=SimpleNamespace(pace_str="5:20"),
            threshold=SimpleNamespace(pace_str="4:50"),
            interval=SimpleNamespace(lower_str="4:10", upper_str="4:25"),
            repetition=SimpleNamespace(pace_str="3:55"),
        ),
    )

    vma, vo2max, vma_method, vma_confidence, paces = await coach_service._load_canonical_performance_signals(
        db, "u1", datetime.now(timezone.utc).date()
    )

    assert vma is None
    assert vma_method is None
    assert vma_confidence == "insufficient"
    assert vo2max == 51.2
    assert paces["z1"] == "5:50-6:20"
    assert paces["z2"] == "5:20"


@pytest.mark.asyncio
async def test_enrichment_functions_work_without_real_network(monkeypatch):
    async def _fake_call(_system, _prompt, _user, _ctx):
        return "ok", True, {"provider": "test"}

    monkeypatch.setattr(llm_coach, "_call_gpt", _fake_call)

    chat, ok_chat, _ = await llm_coach.enrich_chat_response(
        user_message="hello",
        context={"language": "fr", "fitness": {}, "stats_7j": {}, "stats_28j": {}},
        conversation_history=[],
        user_id="u1",
    )
    weekly, ok_weekly, _ = await llm_coach.enrich_weekly_review({"weekly_km": 20}, user_id="u1", language="fr")
    workout, ok_workout, _ = await llm_coach.enrich_workout_analysis({"distance_km": 8}, user_id="u1", language="fr")

    assert ok_chat and chat == "ok"
    assert ok_weekly and weekly == "ok"
    assert ok_workout and workout == "ok"
