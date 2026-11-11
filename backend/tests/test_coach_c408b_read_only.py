"""C408-B — a question about a selected workout is a read-only consultation of the plan.

MongoDB write access is instrumented: the only collections the Coach may write are the chat
history (conversations) and the Coach quota counters. Training V2 mutations (served
prescriptions, snapshots, planned-session memory, invalidation of future prescriptions) must
never happen, and the Training V2 week/today endpoints (which persist) must not be called.
"""

from contextlib import contextmanager
import json
from unittest.mock import AsyncMock, patch

import pytest

from test_coach_contract_unified import _Collection, _FakeDB, _analyze_environment, _trial_access  # sets env first
import server
from test_coach_c393_fallback_quota import _owned_workout, _post
from test_coach_c408_scenarios import DAY, _build, _history, _w
from test_coach_c408_session_coach import _with_workout_detail

pytestmark = pytest.mark.asyncio

ALLOWED_WRITE_COLLECTIONS = {"conversations", "coach_quota_counters"}
WRITE_METHODS = (
    "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
    "delete_many", "find_one_and_update", "find_one_and_replace", "find_one_and_delete", "bulk_write",
)


@contextmanager
def _record_writes(fake_db):
    writes = []
    originals = {}

    def collection_name(collection):
        for name, value in vars(fake_db).items():
            if value is collection:
                return name
        return "?"

    def wrap(method_name, original):
        async def recorder(self, *args, **kwargs):
            writes.append((collection_name(self), method_name))
            return await original(self, *args, **kwargs)
        return recorder

    for name in WRITE_METHODS:
        original = getattr(_Collection, name, None)
        if original is None:
            async def original(self, *a, **k):  # not implemented by the fake: still recorded
                return None
        originals[name] = getattr(_Collection, name, None)
        setattr(_Collection, name, wrap(name, original))
    try:
        yield writes
    finally:
        for name, original in originals.items():
            if original is None:
                delattr(_Collection, name)
            else:
                setattr(_Collection, name, original)


def _forbidden_training_calls():
    return (
        patch("server.get_training_v2_week", AsyncMock(side_effect=AssertionError("week persists"))),
        patch("server.get_today_adaptive_session", AsyncMock(side_effect=AssertionError("today persists"))),
        patch("server.invalidate_future_snapshots", AsyncMock(side_effect=AssertionError("invalidates"))),
    )


def _training_writes(writes):
    return [w for w in writes if w[0] not in ALLOWED_WRITE_COLLECTIONS]


async def _consult(fake_db, *, loader=None, messages=("Commente cette séance.",)):
    week, today, invalidate = _forbidden_training_calls()
    responses = []
    with (
        _analyze_environment(fake_db, _trial_access), _owned_workout(fake_db), _with_workout_detail(),
        week, today, invalidate, _record_writes(fake_db) as writes,
    ):
        if loader is not None:
            with patch("server.load_scoped_workout_coach_evidence", loader):
                for message in messages:
                    responses.append(await _post({"message": message, "workout_id": "w1", "language": "fr"}))
        else:
            for message in messages:
                responses.append(await _post({"message": message, "workout_id": "w1", "language": "fr"}))
        contexts = [call.kwargs["context"] for call in server.llm_coach.enrich_chat_response.await_args_list]
    return responses, contexts, writes


def _evidence(**kwargs):
    from narrative_coach_v3_models import NarrativeCoachV3
    from workout_intelligence_v3_models import WorkoutIntelligenceV3

    _, _, dumped = _build(_w("w1", DAY, hr=133, pace=6.3), _history(), **kwargs)
    narrative = NarrativeCoachV3(headline="h", language="fr", generation_mode="deterministic_fallback")
    return AsyncMock(return_value=(narrative, WorkoutIntelligenceV3(**dumped)))


async def test_initial_analysis_does_not_mutate_training_v2():
    fake_db = _FakeDB()
    responses, contexts, writes = await _consult(fake_db, loader=_evidence())
    assert responses[0].status_code == 200
    assert _training_writes(writes) == []
    assert {w[0] for w in writes} <= ALLOWED_WRITE_COLLECTIONS
    assert any(w == ("conversations", "insert_one") for w in writes)  # chat history still works
    assert '"workout_id"' not in json.dumps(contexts[0])  # C408-C (C421: whole chat context)


async def test_rerun_on_same_session_does_not_mutate_training_v2():
    fake_db = _FakeDB()
    responses, _, writes = await _consult(
        fake_db, loader=_evidence(), messages=("Commente cette séance.", "Commente cette séance."))
    assert [r.status_code for r in responses] == [200, 200]
    assert _training_writes(writes) == []


async def test_historical_prescription_consultation_is_read_only():
    from test_coach_c408_scenarios import _prescription

    fake_db = _FakeDB()
    _, contexts, writes = await _consult(fake_db, loader=_evidence(prescription=_prescription(True)))
    recorded = contexts[0]["athlete_context"]["recorded_prescription"]
    # C421: the snapshot is dated the session day only, so it is not provably earlier: never a known intent
    assert recorded["status"] == "none_usable" and recorded["reason"] == "recording_time_unknown"
    assert "planned_date" not in recorded and "prescribed_workout_type" not in recorded
    assert _training_writes(writes) == []


async def test_missing_snapshot_is_read_only_and_explicit():
    fake_db = _FakeDB()
    _, contexts, writes = await _consult(fake_db, loader=_evidence(prescription=None))
    recorded = contexts[0]["athlete_context"]["recorded_prescription"]
    assert recorded == {"status": "none_usable", "reason": "none_recorded_for_session_date"}
    assert _training_writes(writes) == []


async def test_backend_evidence_error_is_read_only():
    fake_db = _FakeDB()
    loader = AsyncMock(side_effect=RuntimeError("mongo down"))
    responses, contexts, writes = await _consult(fake_db, loader=loader)
    assert responses[0].status_code == 200
    assert contexts[0]["allowed_conclusions"] == []  # V3 unavailable: nothing to relay
    assert "session_type_unknown" in {x["code"] for x in contexts[0]["material_limitations"]}
    assert _training_writes(writes) == []


async def test_selected_session_context_excludes_current_plan_and_title():
    fake_db = _FakeDB()
    _, contexts, _ = await _consult(fake_db, loader=_evidence())
    context = contexts[0]
    for current_only in ("training_week", "today", "readiness", "load", "performance", "paces",
                         "current_training_context", "recent_workouts", "stats_7d", "stats_30d"):
        assert current_only not in context
    assert "name" not in context["session"] and "workout_detail" not in context  # C421: title never sent


async def test_general_chat_without_workout_still_loads_training_payloads():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _trial_access):
        week = server.get_training_v2_week
        await _post({"message": "Combien de séances ?", "language": "fr"})
        week.assert_awaited()


async def test_coach_429_carries_stable_codes():
    from test_coach_contract_unified import _free_access, _run_analyze

    fake_db = _FakeDB()
    for i in range(10):
        assert (await _run_analyze(fake_db, _free_access, message=f"msg-{i}")).status_code == 200
    blocked = await _run_analyze(fake_db, _free_access, message="msg-11")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "coach_monthly_quota_exhausted"
    assert "monthly coach limit" in blocked.json()["detail"]


async def test_rate_limit_429_has_its_own_code():
    import httpx

    with patch.object(server.rate_limiter, "is_limited", return_value=True):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            response = await client.get("/api/coach/history")
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limit_exceeded"
