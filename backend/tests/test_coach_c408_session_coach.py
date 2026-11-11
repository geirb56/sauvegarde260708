"""C408 — session coaching frame, judgment prompt contract and workout continuity.

MongoDB and the LLM are mocked; fixtures are synthetic. LLM answer quality is not assessed here.
"""

from unittest.mock import AsyncMock, patch

import pytest

from coach_context_v2 import build_session_coaching_frame
from test_coach_c393_fallback_quota import _llm, _owned_workout, _post
from test_coach_contract_unified import _FakeDB, _analyze_environment, _trial_access, _free_access
import llm_coach
import server

pytestmark = pytest.mark.asyncio


class _WorkoutContextPayload:
    def model_dump(self, mode: str = "json") -> dict:
        return {"workout_detail": {"id": "w1", "date": "2026-11-01", "type": "run", "avg_hr": 140.0}}


def _with_workout_detail():
    return patch("server.build_coach_context_v2", AsyncMock(return_value=_WorkoutContextPayload()))


def _ctx(**detail):
    base = {"id": "w1", "date": "2026-11-01", "type": "run"}
    base.update(detail)
    return {"workout_detail": base, "goal": {"objective": "10k"}}


def test_frame_reports_available_and_missing_data_without_inventing():
    frame = build_session_coaching_frame(_ctx(avg_pace_display="5:30", avg_hr=140.0, km_splits=[{"k": 1}]))
    assert frame["workout_id"] == "w1" and frame["activity_type"] == "run"
    assert frame["data_available"]["pace"] and frame["data_available"]["avg_hr"]
    assert frame["data_available"]["km_splits"]
    assert {"structured_phases", "elevation", "intensity_classification"} <= set(frame["missing_data"])
    assert frame["athlete_goal_declared"] is True


def test_frame_without_phases_splits_or_goal():
    context = {"workout_detail": {"id": "w2"}}
    frame = build_session_coaching_frame(context, goal_declared=False)
    assert set(frame["missing_data"]) == set(frame["data_available"])
    assert frame["athlete_goal_declared"] is False


def test_frame_never_claims_a_historical_prescription():
    intent = build_session_coaching_frame(_ctx())["session_intent"]
    assert intent["recorded_historical_prescription"] == "not_available_in_this_context"
    assert "unknown" in intent["intent_status"]


def test_frame_absent_without_selected_workout():
    assert build_session_coaching_frame({"goal": {}}) is None
    assert build_session_coaching_frame({"workout_detail": None}) is None


def test_prompt_contract_for_coach_judgment():
    p = llm_coach.SYSTEM_PROMPT_COACH
    for fragment in (
        "ce qui est mesuré, ce qui est plausible et ce qui reste inconnu",
        "ne prouve pas une progression",
        "N'invente aucune donnée physiologique",
        "N'invente ni seuils (LT1/LT2), ni VO2max, ni VMA",
        "la FC maximale d'une séance n'est pas la FC maximale physiologique",
        "conclusions artificielles",
    ):
        assert fragment in p


async def test_frame_and_workout_id_reach_llm_and_followup_keeps_workout():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _trial_access), _owned_workout(fake_db), _with_workout_detail():
        llm = server.llm_coach.enrich_chat_response
        first = await _post({"message": "Analyse cette séance", "workout_id": "w1", "language": "fr"})
        second = await _post({"message": "Et ma FC ?", "workout_id": "w1", "language": "fr"})
        context = llm.await_args.kwargs["context"]
        history = llm.await_args.kwargs["conversation_history"]
    assert first.status_code == second.status_code == 200
    assert "workout_id" not in context["session_coaching_frame"]  # C408-C: no technical id in the prompt
    assert any(m["content"] == "Analyse cette séance" for m in history)
    assert {d["workout_id"] for d in fake_db.conversations._docs} == {"w1"}


async def test_general_chat_has_no_frame_and_old_workout_is_not_reactivated():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _trial_access), _owned_workout(fake_db):
        llm = server.llm_coach.enrich_chat_response
        await _post({"message": "Analyse", "workout_id": "w1", "language": "fr"})
        await _post({"message": "Combien de séances cette semaine ?", "language": "fr"})
        context = llm.await_args.kwargs["context"]
        history = llm.await_args.kwargs["conversation_history"]
    assert "session_coaching_frame" not in context
    assert all(m["content"] != "Analyse" for m in history)


async def test_free_user_workout_request_is_restricted_without_frame():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        llm = server.llm_coach.enrich_chat_response
        response = await _post({"message": "Analyse", "workout_id": "w1", "language": "fr"})
    assert response.status_code == 200
    llm.assert_not_awaited()


async def test_unknown_or_foreign_workout_is_404():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock(return_value=None)),
    ):
        response = await _post({"message": "x", "workout_id": "someone-elses", "language": "en"})
    assert response.status_code == 404


async def test_v3_assessment_reaches_llm_from_a_single_evidence_load():
    from narrative_coach_v3_models import NarrativeCoachV3
    from test_coach_c408_scenarios import DAY, _build, _history, _w
    from workout_intelligence_v3_models import WorkoutIntelligenceV3

    _, _, dumped = _build(_w("w1", DAY, hr=133, pace=6.3), _history())
    narrative = NarrativeCoachV3(headline="h", language="en", generation_mode="deterministic_fallback")
    fake_db = _FakeDB()
    loader = AsyncMock(return_value=(narrative, WorkoutIntelligenceV3(**dumped)))
    with (
        _analyze_environment(fake_db, _trial_access), _owned_workout(fake_db), _with_workout_detail(),
        patch("server.load_scoped_workout_coach_evidence", loader),
    ):
        llm = server.llm_coach.enrich_chat_response
        response = await _post({"message": "Analyse", "workout_id": "w1", "language": "en"})
        frame = llm.await_args.kwargs["context"]["session_coaching_frame"]
    assert response.status_code == 200
    loader.assert_awaited_once()
    assert frame["v3_assessment"]["classification"]["probable_type"] == "easy_run_probable"
    assert llm.await_count == 1


async def test_unavailable_v3_is_explicit_not_empty():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access), _owned_workout(fake_db), _with_workout_detail(),
        patch("server.load_scoped_workout_coach_evidence", AsyncMock(return_value=None)),
    ):
        llm = server.llm_coach.enrich_chat_response
        await _post({"message": "Analyse", "workout_id": "w1", "language": "en"})
        assert llm.await_args.kwargs["context"]["session_coaching_frame"]["v3_assessment"] == "unavailable"
